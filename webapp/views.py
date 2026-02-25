import difflib
import re
import uuid

from allauth.account.views import SignupView as AllauthSignupView
from django.contrib.auth.decorators import login_required
from django.db.models.functions import Lower
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.urls import reverse

from .forms import (
    CreateOrderForm, GuestPreferenceForm, ImportForm,
    MergeToppingForm, PersonProfileForm, PizzaGroupForm, ToppingForm, RestaurantForm,
)
from .models import (
    GroupMembership, Order, OrderedPizza,
    Person, PersonToppingPreference, PizzaGroup, Topping, PizzaRestaurant, RestaurantTopping,
)
from .solver import solve


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
    person, _ = Person.objects.get_or_create(
        user_account=request.user,
        defaults={'name': request.user.email, 'email': request.user.email},
    )

    setup_mode = request.GET.get('setup') == '1'

    # Process pending group join from signup flow (pop so it only runs once)
    pending_token = request.session.pop('pending_group_join', None)
    if pending_token:
        try:
            import uuid as _uuid
            group = PizzaGroup.objects.get(invite_token=_uuid.UUID(pending_token))
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

@login_required
def create_order(request):
    """
    GET:  Display the order creation form (optionally with a proto-order loaded via ?order=pk).
    POST: Handle invite_guests (create proto-order, redirect back) or generate order (run solver).
    """
    person, _ = Person.objects.get_or_create(
        user_account=request.user,
        defaults={'name': request.user.email, 'email': request.user.email},
    )

    if not person.pizza_groups.exists():
        messages.info(request, "You need to belong to a group before creating an order.")
        return redirect('group_list')

    def _get_selected_group(data):
        try:
            group_pk = data.get('group')
            if group_pk:
                return person.pizza_groups.get(pk=group_pk)
        except PizzaGroup.DoesNotExist:
            pass
        return None

    # Load proto-order from query string or POST body
    proto_order = None
    proto_order_id = request.GET.get('order') or request.POST.get('proto_order_id')
    if proto_order_id:
        try:
            proto_order = Order.objects.get(
                pk=int(proto_order_id), host=person, invite_token__isnull=False
            )
            if proto_order.pizzas.exists():
                proto_order = None  # already solved, treat as no proto-order
        except (Order.DoesNotExist, ValueError, TypeError):
            pass

    if request.method == 'POST':
        groups = list(person.pizza_groups.all())
        selected_group = _get_selected_group(request.POST)
        if selected_group is None and proto_order:
            selected_group = proto_order.group

        if 'invite_guests' in request.POST:
            restaurant_id = request.POST.get('restaurant')
            if not restaurant_id or not selected_group:
                messages.error(request, "Please select a restaurant before inviting guests.")
                form = CreateOrderForm(request.POST, host=person, selected_group=selected_group)
                return render(request, 'webapp/order_create.html', {
                    'form': form, 'host': person, 'selected_group': selected_group,
                    'groups': groups, 'can_change_group': len(groups) > 1,
                    'proto_order': None, 'invite_url': None, 'guest_person_ids_str': set(),
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
            return redirect(reverse('create_order') + f'?order={order.pk}&group={selected_group.pk}')

        form = CreateOrderForm(request.POST, host=person, selected_group=selected_group, proto_order=proto_order)
        if form.is_valid():
            data = form.cleaned_data

            if proto_order:
                proto_order.num_pizzas = data['num_pizzas']
                proto_order.optimization_mode = data['optimization_mode']
                proto_order.save()
                proto_order.people.set(set(data['people']) | {person})
                target_order = proto_order
            else:
                target_order = Order.objects.create(
                    host=person,
                    restaurant=data['restaurant'],
                    num_pizzas=data['num_pizzas'],
                    optimization_mode=data['optimization_mode'],
                    group=data['group'],
                )
                target_order.people.set(set(data['people']) | {person})

            try:
                solve(target_order)
            except NotImplementedError:
                messages.warning(
                    request,
                    "The optimization algorithm is not yet implemented. "
                    "The order was created but no pizza assignments were generated."
                )
                return redirect('order_results', order_id=target_order.id)
            except ValueError as e:
                messages.error(request, f"Solver error: {e}")
                if not proto_order:
                    target_order.delete()
                # Fall through to render with form errors
            else:
                messages.success(request, "Pizza order generated successfully!")
                return redirect('order_results', order_id=target_order.id)
    else:
        groups = list(person.pizza_groups.all())
        selected_group = _get_selected_group(request.GET)
        if selected_group is None and proto_order:
            selected_group = proto_order.group
        if selected_group is None and len(groups) == 1:
            selected_group = groups[0]

        if proto_order and selected_group:
            participants_excl_host = proto_order.people.exclude(pk=person.pk)
            form = CreateOrderForm(
                host=person, selected_group=selected_group, proto_order=proto_order,
                initial={
                    'people': list(participants_excl_host.values_list('pk', flat=True)),
                    'num_pizzas': proto_order.num_pizzas,
                    'optimization_mode': proto_order.optimization_mode,
                    'restaurant': proto_order.restaurant.pk,
                    'group': selected_group.pk,
                },
            )
        else:
            form = CreateOrderForm(host=person, selected_group=selected_group)

    # Build invite URL and guest PKs (used in both GET and POST-fall-through renders)
    invite_url = None
    guest_pks = set()
    if proto_order and proto_order.invite_token:
        invite_url = request.build_absolute_uri(
            reverse('order_join', args=[proto_order.invite_token])
        )
        guest_pks = set(proto_order.guest_persons.values_list('pk', flat=True))

    if form.is_bound:
        current_person_pks = set(int(pk) for pk in (form['people'].value() or []))
    else:
        current_person_pks = set(form.initial.get('people') or [])

    return render(request, 'webapp/order_create.html', {
        'form': form,
        'host': person,
        'selected_group': selected_group,
        'groups': groups,
        'can_change_group': len(groups) > 1,
        'proto_order': proto_order,
        'invite_url': invite_url,
        'people': form.fields['people'].queryset,
        'guest_pks': guest_pks,
        'current_person_pks': current_person_pks,
    })


def _compute_pizza_scores(pizza_list):
    """Return a dict mapping pizza.pk -> integer score based on preferences."""
    all_people = {}
    all_toppings = {}
    pizza_data = {}
    for pizza in pizza_list:
        people = list(pizza.people.all())
        toppings = list(pizza.toppings.all())
        pizza_data[pizza.pk] = (people, toppings)
        for p in people:
            all_people[p.pk] = p
        for t in toppings:
            all_toppings[t.pk] = t

    pref_map = {}
    if all_people and all_toppings:
        for person_id, topping_id, pref in PersonToppingPreference.objects.filter(
            person_id__in=all_people.keys(),
            topping_id__in=all_toppings.keys(),
        ).values_list('person_id', 'topping_id', 'preference'):
            pref_map[(person_id, topping_id)] = pref

    scores = {}
    for pizza_pk, (people, toppings) in pizza_data.items():
        score = 0
        for person in people:
            default = PersonToppingPreference.DISLIKE if person.unrated_is_dislike else PersonToppingPreference.NEUTRAL
            for topping in toppings:
                pref = pref_map.get((person.pk, topping.pk), default)
                if pref not in (PersonToppingPreference.NEUTRAL, PersonToppingPreference.ALLERGY):
                    score += pref
        scores[pizza_pk] = score
    return scores


def order_results(request, order_id):
    """Results page for a solved order. Unsolved orders redirect back to create_order."""
    order = get_object_or_404(Order, pk=order_id)
    if not order.pizzas.exists():
        if order.invite_token:
            return redirect(reverse('create_order') + f'?order={order.pk}&group={order.group.pk}')
        return redirect('create_order')
    pizza_list = list(order.pizzas.prefetch_related('toppings', 'people').all())
    guest_person_ids = set(order.guest_persons.values_list('pk', flat=True))
    if request.user.is_staff:
        scores = _compute_pizza_scores(pizza_list)
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
def order_cancel_invite(request, order_id):
    """Host-only POST: delete the proto-order (and its guests), redirect to create_order."""
    if request.method != 'POST':
        return redirect('create_order')
    order = get_object_or_404(Order, pk=order_id, invite_token__isnull=False)
    person = get_object_or_404(Person, user_account=request.user)
    if order.host != person:
        return HttpResponseForbidden("Only the host can cancel this invite.")
    if order.pizzas.exists():
        return redirect('order_results', order_id=order.pk)
    group_pk = order.group.pk
    order.delete()  # cascades to guest Persons
    return redirect(reverse('create_order') + f'?group={group_pk}')


@login_required
def order_people_partial(request, order_id):
    """Partial HTML for the people-selector tags; used by HTMX polling on the create page."""
    order = get_object_or_404(Order, pk=order_id, invite_token__isnull=False)
    person = get_object_or_404(Person, user_account=request.user)
    if order.host != person:
        return HttpResponseForbidden("Only the host can view this.")
    guest_persons = order.guest_persons.all()
    group_members_excl_host = order.group.members.exclude(pk=person.pk)
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
    session_key = f'guest_person_{order.pk}'

    if order.pizzas.exists():
        return render(request, 'webapp/guests/join.html', {
            'order': order,
            'already_solved': True,
        })

    existing_pk = request.session.get(session_key)
    if existing_pk:
        guest = Person.objects.filter(pk=existing_pk, guest_for_order=order).first()
        if guest:
            if request.method == 'POST':
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
                messages.success(request, "Your preferences have been updated!")
                return redirect('order_join', invite_token=invite_token)
            pref_qs = guest.topping_preferences.filter(topping__in=toppings)
            allergy_ids = set(pref_qs.filter(preference=PersonToppingPreference.ALLERGY).values_list('topping_id', flat=True))
            dislike_ids = set(pref_qs.filter(preference=PersonToppingPreference.DISLIKE).values_list('topping_id', flat=True))
            neutral_ids = set(pref_qs.filter(preference=PersonToppingPreference.NEUTRAL).values_list('topping_id', flat=True))
            like_ids = set(pref_qs.filter(preference=PersonToppingPreference.LIKE).values_list('topping_id', flat=True))
            return render(request, 'webapp/guests/join.html', {
                'order': order,
                'toppings': toppings,
                'guest': guest,
                'allergy_ids': allergy_ids,
                'dislike_ids': dislike_ids,
                'neutral_ids': neutral_ids,
                'like_ids': like_ids,
            })

    all_topping_pks = {t.pk for t in toppings}

    if request.method == 'POST':
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
        prefs = []
        for topping in toppings:
            val = request.POST.get(f'pref_{topping.pk}', '0')
            try:
                pref_val = int(val)
            except ValueError:
                pref_val = 0
            prefs.append(PersonToppingPreference(person=guest, topping=topping, preference=pref_val))
        PersonToppingPreference.objects.bulk_create(prefs)
        request.session[session_key] = guest.pk
        messages.success(request, "Your preferences have been saved!")
        return redirect('order_join', invite_token=invite_token)

    return render(request, 'webapp/guests/join.html', {
        'order': order,
        'toppings': toppings,
        'neutral_ids': all_topping_pks,
    })


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

@login_required
def group_list(request):
    person, _ = Person.objects.get_or_create(
        user_account=request.user,
        defaults={'name': request.user.email, 'email': request.user.email},
    )
    memberships = GroupMembership.objects.filter(person=person).select_related('group')
    return render(request, 'webapp/groups/list.html', {'memberships': memberships})


@login_required
def group_create(request):
    person, _ = Person.objects.get_or_create(
        user_account=request.user,
        defaults={'name': request.user.email, 'email': request.user.email},
    )
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
    person = get_object_or_404(Person, user_account=request.user)
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
    person, _ = Person.objects.get_or_create(
        user_account=request.user,
        defaults={'name': request.user.email, 'email': request.user.email},
    )
    _, created = GroupMembership.objects.get_or_create(group=group, person=person)
    if created:
        messages.success(request, f"You have joined '{group.name}'.")
    else:
        messages.info(request, f"You are already a member of '{group.name}'.")
    return redirect('group_detail', pk=group.pk)


@login_required
def group_reset_invite(request, pk):
    if request.method != 'POST':
        return redirect('group_detail', pk=pk)
    group = get_object_or_404(PizzaGroup, pk=pk)
    person = get_object_or_404(Person, user_account=request.user)
    membership = get_object_or_404(GroupMembership, group=group, person=person)
    if not membership.is_admin:
        return HttpResponseForbidden("Only admins can reset the invite link.")
    import uuid as _uuid
    group.invite_token = _uuid.uuid4()
    group.save()
    messages.success(request, "Invite link has been reset. The old link will no longer work.")
    return redirect('group_detail', pk=pk)


@login_required
def group_remove_member(request, pk, person_pk):
    if request.method != 'POST':
        return redirect('group_detail', pk=pk)
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
def topping_create(request):
    if not request.user.is_staff:
        return HttpResponseForbidden()
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
def topping_edit(request, pk):
    if not request.user.is_staff:
        return HttpResponseForbidden()
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
def topping_merge(request, pk):
    if not request.user.is_staff:
        return HttpResponseForbidden()
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
def topping_delete(request, pk):
    if not request.user.is_staff:
        return HttpResponseForbidden()
    topping = get_object_or_404(Topping, pk=pk)
    if request.method == 'POST':
        name = str(topping)
        topping.delete()
        messages.success(request, f"Topping '{name}' deleted.")
        return redirect('topping_list')
    return render(request, 'webapp/toppings/confirm_delete.html', {'topping': topping})


# ---------------------------------------------------------------------------
# Restaurant CRUD
# ---------------------------------------------------------------------------

@login_required
def restaurant_list(request):
    person = get_object_or_404(Person, user_account=request.user)
    group_ids = person.pizza_groups.values_list('pk', flat=True)
    restaurants = (
        PizzaRestaurant.objects
        .filter(group__in=group_ids)
        .select_related('group')
        .prefetch_related('toppings')
        .order_by('name')
    )
    return render(request, 'webapp/restaurants/list.html', {'restaurants': restaurants})


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
        'can_change_group': False,
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


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@login_required
def import_data(request):
    if not request.user.is_staff:
        return HttpResponseForbidden()

    context = {'form': ImportForm()}

    if request.method == 'POST':
        form = ImportForm(request.POST, request.FILES)
        context['form'] = form
        if form.is_valid():
            content = request.FILES['file'].read().decode('utf-8')
            lines = [line.strip() for line in content.splitlines()]

            section = None
            toppings_created = 0
            toppings_existed = 0
            restaurants_created = 0
            restaurants_existed = 0
            warnings = []

            for line in lines:
                if not line or line.startswith('#'):
                    continue
                if line == '[toppings]':
                    section = 'toppings'
                    continue
                if line == '[restaurants]':
                    section = 'restaurants'
                    continue

                if section == 'toppings':
                    _, created = Topping.objects.get_or_create(name=line)
                    if created:
                        toppings_created += 1
                    else:
                        toppings_existed += 1

                elif section == 'restaurants':
                    if ':' in line:
                        restaurant_name, topping_str = line.split(':', 1)
                        restaurant_name = restaurant_name.strip()
                        topping_names = [t.strip() for t in topping_str.split(',') if t.strip()]
                    else:
                        restaurant_name = line
                        topping_names = []

                    if not restaurant_name:
                        warnings.append(f"Could not parse restaurant line: {line!r}")
                        continue

                    restaurant, created = PizzaRestaurant.objects.get_or_create(name=restaurant_name)
                    if created:
                        restaurants_created += 1
                    else:
                        restaurants_existed += 1

                    for topping_name in topping_names:
                        topping, t_created = Topping.objects.get_or_create(name=topping_name)
                        if t_created:
                            toppings_created += 1
                        RestaurantTopping.objects.get_or_create(restaurant=restaurant, topping=topping)

                else:
                    warnings.append(f"Line outside any section: {line!r}")

            context['results'] = {
                'toppings_created': toppings_created,
                'toppings_existed': toppings_existed,
                'restaurants_created': restaurants_created,
                'restaurants_existed': restaurants_existed,
            }
            context['warnings'] = warnings

    return render(request, 'webapp/import.html', context)
