import difflib
import re
import uuid

from allauth.account.views import SignupView as AllauthSignupView
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models.functions import Lower
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import (
    NewOrderForm, DraftOrderForm, GuestPreferenceForm,
    MergeToppingForm, PersonProfileForm, PizzaGroupForm, ToppingForm, RestaurantForm,
    CloneRestaurantForm,
)
from .models import (
    GroupMembership, Order, OrderedPizza,
    Person, PersonToppingPreference, PizzaGroup, Topping, PizzaRestaurant, RestaurantTopping,
)
from .solver import solve
from .utils import compute_pizza_scores

# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

_GROUP_JOIN_RE = re.compile(r'^/groups/join/([0-9a-f-]{36})/?$')


class CustomSignupView(AllauthSignupView):
    def get_success_url(self):
        next_url = self.get_next_url() or ''
        match = _GROUP_JOIN_RE.match(next_url)
        if match:
            self.request.session['pending_group_join'] = match.group(1)
        return '/profile/edit/?setup=1'


@login_required
def profile_edit(request):
    """Display and handle the profile/preference edit form."""
    person = Person.get_from_request(request)
    setup_mode = request.GET.get('setup') == '1'

    # Process pending group join from the signup flow (pop so it only runs once)
    pending_token = request.session.pop('pending_group_join', None)
    if pending_token:
        try:
            group = PizzaGroup.objects.get(invite_token=uuid.UUID(pending_token))
            _, created = GroupMembership.objects.get_or_create(group=group, person=person)
            if created:
                messages.success(request, f"You've been added to '{group.name}'.")
        except (ValueError, PizzaGroup.DoesNotExist):
            pass

    toppings = Topping.objects.order_by('name')

    pref_qs = PersonToppingPreference.objects.filter(person=person)
    allergy_ids = set(pref_qs.filter(preference=PersonToppingPreference.ALLERGY).values_list('topping_id', flat=True))
    dislike_ids = set(pref_qs.filter(preference=PersonToppingPreference.DISLIKE).values_list('topping_id', flat=True))
    neutral_ids = set(pref_qs.filter(preference=PersonToppingPreference.NEUTRAL).values_list('topping_id', flat=True))
    like_ids = set(pref_qs.filter(preference=PersonToppingPreference.LIKE).values_list('topping_id', flat=True))

    if request.method == 'POST':
        form = PersonProfileForm(request.POST, instance=person)
        if form.is_valid():
            form.save()
            new_prefs = {}

            for topping in toppings:
                val_str = request.POST.get(f'pref_{topping.pk}')
                if val_str == 'allergy':
                    new_prefs[topping.pk] = PersonToppingPreference.ALLERGY
                elif val_str == 'dislike':
                    new_prefs[topping.pk] = PersonToppingPreference.DISLIKE
                elif val_str == 'neutral':
                    new_prefs[topping.pk] = PersonToppingPreference.NEUTRAL
                elif val_str == 'like':
                    new_prefs[topping.pk] = PersonToppingPreference.LIKE

            to_delete = [t.pk for t in toppings if t.pk not in new_prefs]
            if to_delete:
                PersonToppingPreference.objects.filter(person=person, topping_id__in=to_delete).delete()
            if new_prefs:
                PersonToppingPreference.objects.bulk_create(
                    [PersonToppingPreference(person=person, topping_id=tid, preference=pref)
                     for tid, pref in new_prefs.items()],
                    update_conflicts=True,
                    unique_fields=['person', 'topping'],
                    update_fields=['preference'],
                )

            messages.success(request, "Your preferences have been saved.")
            if setup_mode:
                return redirect('index')
            return redirect('profile_edit')
    else:
        form = PersonProfileForm(instance=person)

    template = 'webapp/profile/setup.html' if setup_mode else 'webapp/profile/edit.html'
    return render(request, template, {
        'form': form,
        'toppings': toppings,
        'allergy_ids': allergy_ids,
        'dislike_ids': dislike_ids,
        'neutral_ids': neutral_ids,
        'like_ids': like_ids,
    })


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def _run_solver(request, order):
    """Run the solver on an order. Returns a redirect response, or None to re-render."""
    try:
        solve(order)
    except NotImplementedError:
        messages.warning(
            request,
            "The optimization algorithm is not yet implemented. "
            "The order was created but no pizza assignments were generated."
        )
        return redirect('order_results', order_id=order.id)
    except ValueError as e:
        messages.error(request, f"Solver error: {e}")
        return None
    messages.success(request, "Pizza order generated successfully!")
    return redirect('order_results', order_id=order.id)

@login_required
def order_select_group(request):
    """Redirect single-group users straight to the order form; multi-group users pick a group."""
    person = Person.get_from_request(request)
    groups = list(person.pizza_groups.all())
    if not groups:
        messages.info(request, "You need to belong to a group before creating an order.")
        return redirect('group_list')
    if len(groups) == 1:
        return redirect('new_order', group_id=groups[0].pk)
    if request.method == 'POST':
        try:
            group = person.pizza_groups.get(pk=request.POST.get('group'))
            return redirect('new_order', group_id=group.pk)
        except PizzaGroup.DoesNotExist:
            pass
    return render(request, 'webapp/order_select_group.html', {'groups': groups})


@login_required
def new_order(request, group_id):
    """
    GET:  Display the blank new-order form.
    POST: Handle invite_guests (create proto-order, redirect to draft) or generate order (run solver).
    """
    person = Person.get_from_request(request)
    selected_group = get_object_or_404(PizzaGroup, pk=group_id)
    get_object_or_404(GroupMembership, group=selected_group, person=person)
    can_change_group = person.pizza_groups.count() > 1

    if request.method == 'POST':
        if 'invite_guests' in request.POST:
            restaurant_id = request.POST.get('restaurant')
            if not restaurant_id:
                messages.error(request, "Please select a restaurant before inviting guests.")
                form = NewOrderForm(request.POST, host=person, selected_group=selected_group)
                return render(request, 'webapp/order_new.html', {
                    'form': form, 'host': person, 'selected_group': selected_group,
                    'can_change_group': can_change_group,
                    'people': form.fields['people'].queryset, 'current_person_pks': set(),
                })
            restaurant = get_object_or_404(PizzaRestaurant, pk=restaurant_id, group=selected_group)
            order = Order.objects.create(
                host=person,
                group=selected_group,
                restaurant=restaurant,
                num_pizzas=1,
                optimization_mode='maximize_likes',
                invite_token=uuid.uuid4(),
            )
            order.people.add(person)
            return redirect('draft_order', group_id=selected_group.pk, order_id=order.pk)

        form = NewOrderForm(request.POST, host=person, selected_group=selected_group)
        if form.is_valid():
            data = form.cleaned_data
            target_order = Order.objects.create(
                host=person,
                restaurant=data['restaurant'],
                num_pizzas=data['num_pizzas'],
                optimization_mode=data['optimization_mode'],
                shareability_bonus_weight=data['shareability_bonus_weight'],
                group=selected_group,
            )
            target_order.people.set(set(data['people']) | {person})
            result = _run_solver(request, target_order)
            if result is not None:
                return result
    else:
        form = NewOrderForm(host=person, selected_group=selected_group)

    if form.is_bound:
        current_person_pks = set(int(pk) for pk in (form['people'].value() or []))
    else:
        current_person_pks = set()

    return render(request, 'webapp/order_new.html', {
        'form': form,
        'host': person,
        'selected_group': selected_group,
        'can_change_group': can_change_group,
        'people': form.fields['people'].queryset,
        'current_person_pks': current_person_pks,
    })


@login_required
def draft_order(request, group_id, order_id):
    """
    GET:  Display the draft order form (locked restaurant, invite link, HTMX people polling).
    POST: Generate the order (run solver), updating the proto-order in place.
    """
    person = Person.get_from_request(request)
    selected_group = get_object_or_404(PizzaGroup, pk=group_id)
    get_object_or_404(GroupMembership, group=selected_group, person=person)
    can_change_group = person.pizza_groups.count() > 1

    proto_order = get_object_or_404(Order, pk=order_id, host=person, invite_token__isnull=False)
    if proto_order.pizzas.exists():
        return redirect('order_results', order_id=proto_order.pk)

    invite_url = request.build_absolute_uri(reverse('order_join', args=[proto_order.invite_token]))
    guest_pks = set(proto_order.guest_persons.values_list('pk', flat=True))

    if request.method == 'POST':
        form = DraftOrderForm(request.POST, host=person, selected_group=selected_group, proto_order=proto_order)
        if form.is_valid():
            data = form.cleaned_data
            proto_order.num_pizzas = data['num_pizzas']
            proto_order.optimization_mode = data['optimization_mode']
            proto_order.shareability_bonus_weight = data['shareability_bonus_weight']
            proto_order.save()
            proto_order.people.set(set(data['people']) | {person})
            result = _run_solver(request, proto_order)
            if result is not None:
                return result
    else:
        participants_excl_host = proto_order.people.exclude(pk=person.pk)
        form = DraftOrderForm(
            host=person, selected_group=selected_group, proto_order=proto_order,
            initial={
                'people': list(participants_excl_host.values_list('pk', flat=True)),
                'num_pizzas': proto_order.num_pizzas,
                'optimization_mode': proto_order.optimization_mode,
                'shareability_bonus_weight': proto_order.shareability_bonus_weight,
            },
        )

    if form.is_bound:
        current_person_pks = set(int(pk) for pk in (form['people'].value() or []))
    else:
        current_person_pks = set(form.initial.get('people') or [])

    return render(request, 'webapp/order_draft.html', {
        'form': form,
        'host': person,
        'selected_group': selected_group,
        'can_change_group': can_change_group,
        'proto_order': proto_order,
        'invite_url': invite_url,
        'people': form.fields['people'].queryset,
        'guest_pks': guest_pks,
        'current_person_pks': current_person_pks,
    })


def order_results(request, order_id):
    """Results page for a solved order. Unsolved orders redirect back to create_order."""
    order = get_object_or_404(Order, pk=order_id)
    person = getattr(request.user, 'person_profile', None) if request.user.is_authenticated else None
    if not person or not person.pizza_groups.filter(pk=order.group_id).exists():
        return HttpResponseForbidden("You don't have permission to view this order.")
    if not order.pizzas.exists():
        if order.invite_token:
            return redirect('draft_order', group_id=order.group.pk, order_id=order.pk)
        return redirect('new_order', group_id=order.group.pk)
    pizza_list = list(order.pizzas.prefetch_related('toppings', 'people').all())
    guest_person_ids = set(order.guest_persons.values_list('pk', flat=True))
    if request.user.is_staff:
        scores = compute_pizza_scores(pizza_list)
        pizzas_with_scores = [(p, scores[p.pk]) for p in pizza_list]
    else:
        pizzas_with_scores = [(p, None) for p in pizza_list]
    return render(request, 'webapp/order_results.html', {
        'order': order,
        'pizzas_with_scores': pizzas_with_scores,
        'guest_person_ids': guest_person_ids,
    })


# ---------------------------------------------------------------------------
# Guest views
# ---------------------------------------------------------------------------

@login_required
@require_POST
def order_cancel_invite(request, order_id):
    """Host-only POST: delete the proto-order (and its guests), redirect to create_order."""
    order = get_object_or_404(Order, pk=order_id, invite_token__isnull=False)
    person = get_object_or_404(Person, user_account=request.user)
    if order.host != person:
        return HttpResponseForbidden("Only the host can cancel this invite.")
    if order.pizzas.exists():
        return redirect('order_results', order_id=order.pk)
    group_pk = order.group.pk
    order.delete()  # cascades to guest Persons
    return redirect('new_order', group_id=group_pk)


@login_required
def order_people_partial(request, order_id):
    """Partial HTML for the people-selector tags; used by HTMX polling on the create page."""
    order = get_object_or_404(Order, pk=order_id, invite_token__isnull=False)
    person = get_object_or_404(Person, user_account=request.user)
    if order.host != person:
        return HttpResponseForbidden("Only the host can view this.")
    guest_persons = order.guest_persons.all()
    group_members_excl_host = order.group.members.exclude(pk=person.pk)
    # TODO: figure out why this isn't redundant
    people = (group_members_excl_host | guest_persons).distinct()
    return render(request, 'webapp/_people_tags_partial.html', {
        'people': people,
        'guest_pks': set(guest_persons.values_list('pk', flat=True)),
        'current_person_pks': set(order.people.exclude(pk=person.pk).values_list('pk', flat=True)),
    })


def order_join(request, invite_token):
    """No-auth guest join page. Session dedup prevents duplicate entries."""
    order = get_object_or_404(Order, invite_token=invite_token)
    toppings = list(order.restaurant.toppings.all().order_by('name'))
    all_topping_pks = {t.pk for t in toppings}
    session_key = f'guest_person_{order.pk}'

    if order.pizzas.exists():
        return render(request, 'webapp/guests/join.html', {
            'order': order,
            'already_solved': True,
        })

    existing_pk = request.session.get(session_key)
    guest = None
    if existing_pk:
        guest = Person.objects.filter(pk=existing_pk, guest_for_order=order).first()
    if request.method == 'POST':
        # create the guest if they don't exist
        if not guest:
            name = request.POST.get('name', '').strip()
            if not name:
                return render(request, 'webapp/guests/join.html', {
                    'order': order,
                    'toppings': toppings,
                    'error': 'Please enter your name.',
                    'neutral_ids': all_topping_pks,
                })
            guest = Person.objects.create(name=name, email='', guest_for_order=order)
            order.people.add(guest)
            request.session[session_key] = guest.pk

        prefs = []
        for topping in toppings:
            val = request.POST.get(f'pref_{topping.pk}', '0')
            try:
                pref_val = int(val)
            except ValueError:
                pref_val = 0
            prefs.append(PersonToppingPreference(person=guest, topping=topping, preference=pref_val))
        PersonToppingPreference.objects.bulk_create(
            prefs,
            update_conflicts=True,
            unique_fields=['person', 'topping'],
            update_fields=['preference'],
        )
        messages.success(request, f"Your preferences have been saved!")
        return redirect('order_join', invite_token=invite_token)

    allergy_ids = set()
    dislike_ids = set()
    neutral_ids = all_topping_pks
    like_ids = set()
    if guest:
        # existing + get -> get split toppings for display + render
        pref_qs = guest.topping_preferences.filter(topping__in=toppings)
        allergy_ids = set(
            pref_qs.filter(preference=PersonToppingPreference.ALLERGY).values_list('topping_id', flat=True))
        dislike_ids = set(
            pref_qs.filter(preference=PersonToppingPreference.DISLIKE).values_list('topping_id', flat=True))
        neutral_ids = set(
            pref_qs.filter(preference=PersonToppingPreference.NEUTRAL).values_list('topping_id', flat=True))
        like_ids = set(
            pref_qs.filter(preference=PersonToppingPreference.LIKE).values_list('topping_id', flat=True))

    return render(request, 'webapp/guests/join.html', {
        'order': order,
        'toppings': toppings,
        'guest': guest,
        'allergy_ids': allergy_ids,
        'dislike_ids': dislike_ids,
        'neutral_ids': neutral_ids,
        'like_ids': like_ids,
    })


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

@login_required
def group_list(request):
    person = Person.get_from_request(request)
    memberships = GroupMembership.objects.filter(person=person).select_related('group')
    return render(request, 'webapp/groups/list.html', {'memberships': memberships})


@login_required
def group_create(request):
    person = Person.get_from_request(request)
    if request.method == 'POST':
        form = PizzaGroupForm(request.POST)
        if form.is_valid():
            group = form.save()
            GroupMembership.objects.create(group=group, person=person, is_admin=True)
            messages.success(request, f"Group '{group.name}' created.")
            return redirect('group_detail', pk=group.pk)
    else:
        form = PizzaGroupForm()
    return render(request, 'webapp/groups/form.html', {'form': form, 'action': 'Create'})


@login_required
def group_detail(request, pk):
    group = get_object_or_404(PizzaGroup, pk=pk)
    person = Person.get_from_request(request)
    membership = get_object_or_404(GroupMembership, group=group, person=person)
    memberships = GroupMembership.objects.filter(group=group).select_related('person')
    invite_url = request.build_absolute_uri(f'/groups/join/{group.invite_token}/')
    return render(request, 'webapp/groups/detail.html', {
        'group': group,
        'memberships': memberships,
        'is_admin': membership.is_admin,
        'invite_url': invite_url,
    })


@login_required
def group_join(request, token):
    group = get_object_or_404(PizzaGroup, invite_token=token)
    person = Person.get_from_request(request)
    _, created = GroupMembership.objects.get_or_create(group=group, person=person)
    if created:
        messages.success(request, f"You have joined '{group.name}'.")
    else:
        messages.info(request, f"You are already a member of '{group.name}'.")
    return redirect('group_detail', pk=group.pk)


@login_required
@require_POST
def group_reset_invite(request, pk):
    group = get_object_or_404(PizzaGroup, pk=pk)
    person = get_object_or_404(Person, user_account=request.user)
    membership = get_object_or_404(GroupMembership, group=group, person=person)
    if not membership.is_admin:
        return HttpResponseForbidden("Only admins can reset the invite link.")
    group.invite_token = uuid.uuid4()
    group.save()
    messages.success(request, "Invite link has been reset. The old link will no longer work.")
    return redirect('group_detail', pk=pk)


@login_required
@require_POST
def group_remove_member(request, pk, person_pk):
    group = get_object_or_404(PizzaGroup, pk=pk)
    requester = get_object_or_404(Person, user_account=request.user)
    requester_membership = get_object_or_404(GroupMembership, group=group, person=requester)
    if not requester_membership.is_admin:
        return HttpResponseForbidden("Only admins can remove members.")
    target_person = get_object_or_404(Person, pk=person_pk)
    GroupMembership.objects.filter(group=group, person=target_person).delete()
    messages.success(request, f"{target_person.name} removed from {group.name}.")
    return redirect('group_detail', pk=pk)


@login_required
def group_delete(request, pk):
    group = get_object_or_404(PizzaGroup, pk=pk)
    person = get_object_or_404(Person, user_account=request.user)
    membership = get_object_or_404(GroupMembership, group=group, person=person)
    if not membership.is_admin:
        return HttpResponseForbidden("Only admins can delete groups.")
    if request.method == 'POST':
        name = group.name
        group.delete()
        messages.success(request, f"Group '{name}' deleted.")
        return redirect('group_list')
    return render(request, 'webapp/groups/confirm_delete.html', {'group': group})


# ---------------------------------------------------------------------------
# Topping CRUD
# ---------------------------------------------------------------------------

@login_required
def topping_list(request):
    toppings = Topping.objects.order_by(Lower('name'))
    return render(request, 'webapp/toppings/list.html', {'toppings': toppings})


@login_required
@staff_member_required
def topping_create(request):
    if request.method == 'POST':
        form = ToppingForm(request.POST)
        if form.is_valid():
            topping = form.save()
            messages.success(request, f"Topping '{topping}' created.")
            return redirect('topping_list')
    else:
        form = ToppingForm()
    return render(request, 'webapp/toppings/form.html', {'form': form, 'action': 'Create'})


@login_required
@staff_member_required
def topping_edit(request, pk):
    topping = get_object_or_404(Topping, pk=pk)
    if request.method == 'POST':
        form = ToppingForm(request.POST, instance=topping)
        if form.is_valid():
            topping = form.save()
            messages.success(request, f"Topping '{topping}' updated.")
            return redirect('topping_list')
    else:
        form = ToppingForm(instance=topping)
    return render(request, 'webapp/toppings/form.html', {'form': form, 'action': 'Edit', 'topping': topping})


@login_required
@staff_member_required
def topping_merge(request, pk):
    topping = get_object_or_404(Topping, pk=pk)

    if request.method == 'POST':
        form = MergeToppingForm(request.POST, exclude_pk=pk)
        if form.is_valid():
            target = form.cleaned_data['target']

            for pref in PersonToppingPreference.objects.filter(topping=topping):
                if PersonToppingPreference.objects.filter(person=pref.person, topping=target).exists():
                    pref.delete()
                else:
                    pref.topping = target
                    pref.save()

            for rt in RestaurantTopping.objects.filter(topping=topping):
                if RestaurantTopping.objects.filter(restaurant=rt.restaurant, topping=target).exists():
                    rt.delete()
                else:
                    rt.topping = target
                    rt.save()

            for pizza in OrderedPizza.objects.filter(toppings=topping):
                pizza.toppings.add(target)
                pizza.toppings.remove(topping)

            name = str(topping)
            topping.delete()
            messages.success(request, f"Topping '{name}' merged into '{target}'.")
            return redirect('topping_list')
    else:
        others = Topping.objects.exclude(pk=pk)
        best = max(
            others,
            key=lambda t: difflib.SequenceMatcher(None, topping.name.lower(), t.name.lower()).ratio(),
            default=None,
        )
        form = MergeToppingForm(exclude_pk=pk, initial={'target': best})

    return render(request, 'webapp/toppings/merge.html', {'form': form, 'topping': topping})


@login_required
@staff_member_required
def topping_delete(request, pk):
    topping = get_object_or_404(Topping, pk=pk)
    if request.method == 'POST':
        name = str(topping)
        topping.delete()
        messages.success(request, f"Topping '{name}' deleted.")
        return redirect('topping_list')
    return render(request, 'webapp/toppings/confirm_delete.html', {'topping': topping})


@login_required
@staff_member_required
def staff_preferences(request):
    all_groups = PizzaGroup.objects.order_by(Lower('name'))

    selected_group = None
    members = []
    toppings = []
    matrix = []

    group_pk = request.GET.get('group')
    if group_pk:
        try:
            selected_group = PizzaGroup.objects.get(pk=group_pk)
        except PizzaGroup.DoesNotExist:
            pass

    if selected_group is not None:
        members = list(
            selected_group.members
            .filter(guest_for_order__isnull=True)
            .order_by(Lower('name'))
        )
        toppings = list(Topping.objects.order_by(Lower('name')))

        prefs_qs = PersonToppingPreference.objects.filter(
            person_id__in=[m.pk for m in members],
            topping_id__in=[t.pk for t in toppings],
        ).values('person_id', 'topping_id', 'preference')

        pref_lookup = {(row['topping_id'], row['person_id']): row['preference'] for row in prefs_qs}

        pref_label = {
            PersonToppingPreference.ALLERGY: 'allergy',
            PersonToppingPreference.DISLIKE: 'dislike',
            PersonToppingPreference.NEUTRAL: 'neutral',
            PersonToppingPreference.LIKE:    'like',
        }
        default_label = {
            m.pk: 'dislike' if m.unrated_is_dislike else 'neutral'
            for m in members
        }

        matrix = []
        for t in toppings:
            cells = []
            for m in members:
                explicit = pref_lookup.get((t.pk, m.pk))
                if explicit is None:
                    cells.append({'label': default_label[m.pk], 'is_default': True})
                else:
                    cells.append({'label': pref_label[explicit], 'is_default': False})
            matrix.append({'topping': t, 'cells': cells})

    return render(request, 'webapp/staff/preferences.html', {
        'all_groups': all_groups,
        'selected_group': selected_group,
        'members': members,
        'toppings': toppings,
        'matrix': matrix,
    })


# ---------------------------------------------------------------------------
# Restaurant CRUD
# ---------------------------------------------------------------------------

@login_required
def restaurant_list(request):
    person = get_object_or_404(Person, user_account=request.user)
    group_ids = list(person.pizza_groups.values_list('pk', flat=True))
    restaurants = (
        PizzaRestaurant.objects
        .filter(group__in=group_ids)
        .select_related('group')
        .prefetch_related('toppings')
        .order_by('name')
    )
    return render(request, 'webapp/restaurants/list.html', {
        'restaurants': restaurants,
        'can_clone': len(group_ids) > 1,
    })


@login_required
def restaurant_create(request):
    person = get_object_or_404(Person, user_account=request.user)
    groups = list(person.pizza_groups.all())

    def _get_selected_group(data):
        try:
            group_pk = data.get('group')
            if group_pk:
                return person.pizza_groups.get(pk=group_pk)
        except PizzaGroup.DoesNotExist:
            pass
        return None

    if request.method == 'POST':
        selected_group = _get_selected_group(request.POST)
        if not selected_group:
            messages.error(request, "A valid group is required to create a restaurant.")
            return redirect('restaurant_create')
        form = RestaurantForm(request.POST)
        if form.is_valid():
            restaurant = form.save(commit=False)
            restaurant.group = selected_group
            restaurant.save()
            RestaurantTopping.objects.bulk_create([
                RestaurantTopping(restaurant=restaurant, topping=topping)
                for topping in form.cleaned_data['toppings']
            ])
            messages.success(request, f"Restaurant '{restaurant}' created.")
            return redirect('restaurant_list')
    else:
        selected_group = _get_selected_group(request.GET)
        if selected_group is None and len(groups) == 1:
            selected_group = groups[0]
        form = RestaurantForm()

    return render(request, 'webapp/restaurants/form.html', {
        'form': form,
        'action': 'Create',
        'selected_group': selected_group,
        'groups': groups,
        'can_change_group': len(groups) > 1,
    })


@login_required
def restaurant_edit(request, pk):
    restaurant = get_object_or_404(PizzaRestaurant, pk=pk)
    person = get_object_or_404(Person, user_account=request.user)
    if not restaurant.group or not person.pizza_groups.filter(pk=restaurant.group_id).exists():
        return HttpResponseForbidden("You don't have permission to edit this restaurant.")
    if request.method == 'POST':
        form = RestaurantForm(request.POST, instance=restaurant)
        if form.is_valid():
            restaurant = form.save()
            selected = set(form.cleaned_data['toppings'])
            existing = set(restaurant.toppings.all())
            RestaurantTopping.objects.filter(restaurant=restaurant, topping__in=existing - selected).delete()
            RestaurantTopping.objects.bulk_create([
                RestaurantTopping(restaurant=restaurant, topping=topping)
                for topping in selected - existing
            ])
            messages.success(request, f"Restaurant '{restaurant}' updated.")
            return redirect('restaurant_list')
    else:
        form = RestaurantForm(instance=restaurant)
    return render(request, 'webapp/restaurants/form.html', {
        'form': form,
        'action': 'Edit',
        'restaurant': restaurant,
        'selected_group': restaurant.group,
        'can_chxange_group': False,
    })


@login_required
def restaurant_delete(request, pk):
    restaurant = get_object_or_404(PizzaRestaurant, pk=pk)
    person = get_object_or_404(Person, user_account=request.user)
    if not restaurant.group or not person.pizza_groups.filter(pk=restaurant.group_id).exists():
        return HttpResponseForbidden("You don't have permission to delete this restaurant.")
    if request.method == 'POST':
        name = str(restaurant)
        restaurant.delete()
        messages.success(request, f"Restaurant '{name}' deleted.")
        return redirect('restaurant_list')
    return render(request, 'webapp/restaurants/confirm_delete.html', {'restaurant': restaurant})


@login_required
def restaurant_clone(request, pk):
    restaurant = get_object_or_404(PizzaRestaurant, pk=pk)
    person = get_object_or_404(Person, user_account=request.user)
    if not restaurant.group or not person.pizza_groups.filter(pk=restaurant.group_id).exists():
        return HttpResponseForbidden("You don't have permission to clone this restaurant.")
    other_groups = list(person.pizza_groups.exclude(pk=restaurant.group_id))
    if not other_groups:
        messages.error(request, "You need to be in at least one other group to clone a restaurant.")
        return redirect('restaurant_list')
    if request.method == 'POST':
        form = CloneRestaurantForm(request.POST, restaurant=restaurant, person=person)
        if form.is_valid():
            target_group = form.cleaned_data['target_group']
            name = form.cleaned_data['name']
            new_restaurant = PizzaRestaurant.objects.create(name=name, group=target_group)
            RestaurantTopping.objects.bulk_create([
                RestaurantTopping(restaurant=new_restaurant, topping=topping)
                for topping in restaurant.toppings.all()
            ])
            messages.success(request, f"Restaurant '{new_restaurant}' cloned to {target_group}.")
            return redirect('restaurant_list')
    else:
        form = CloneRestaurantForm(restaurant=restaurant, person=person)
    return render(request, 'webapp/restaurants/clone.html', {
        'form': form,
        'restaurant': restaurant,
    })

