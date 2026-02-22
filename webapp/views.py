import difflib
import uuid

from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models.functions import Lower
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.template.loader import render_to_string

from django.http import HttpResponseForbidden

from .forms import CreateOrderForm, GuestSetupForm, ImportForm, MergeToppingForm, PersonProfileForm, ToppingForm, VendorForm
from .models import Order, OrderedPizza, Person, PersonToppingPreference, Topping, PizzaVendor, VendorTopping
from .solver import solve

GUEST_COOKIE_NAME = 'pizza_guest_token'
GUEST_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


def get_person_from_request(request):
    """Returns Person from logged-in user or guest cookie, or None."""
    if request.user.is_authenticated:
        try:
            return request.user.person_profile
        except Person.DoesNotExist:
            pass
    token_str = request.COOKIES.get(GUEST_COOKIE_NAME)
    if token_str:
        try:
            return Person.objects.get(guest_token=uuid.UUID(token_str))
        except (ValueError, Person.DoesNotExist):
            pass
    return None


def guest_setup(request):
    """GET: show email form (or redirect if cookie valid). POST: look up or create person."""
    if request.user.is_authenticated:
        return redirect('profile_edit')

    if request.method == 'GET':
        token_str = request.COOKIES.get(GUEST_COOKIE_NAME)
        if token_str:
            try:
                Person.objects.get(guest_token=uuid.UUID(token_str))
                return redirect('profile_edit')
            except (ValueError, Person.DoesNotExist):
                pass
        form = GuestSetupForm()
        return render(request, 'webapp/profile/setup.html', {'form': form})

    form = GuestSetupForm(request.POST)
    if not form.is_valid():
        return render(request, 'webapp/profile/setup.html', {'form': form})

    email = form.cleaned_data['email']
    try:
        person = Person.objects.get(email__iexact=email)
        # Send magic link email
        magic_url = request.build_absolute_uri(f'/profile/magic/{person.guest_token}/')
        body = render_to_string('webapp/email/magic_link.txt', {'magic_url': magic_url})
        send_mail(
            subject='Your Pizza Solver login link',
            message=body,
            from_email=None,
            recipient_list=[email],
        )
        return render(request, 'webapp/profile/setup_sent.html', {'email': email})
    except Person.DoesNotExist:
        person = Person.objects.create(name=email, email=email)
        response = redirect('profile_edit')
        response.set_cookie(
            GUEST_COOKIE_NAME,
            str(person.guest_token),
            max_age=GUEST_COOKIE_MAX_AGE,
            httponly=True,
            samesite='Lax',
        )
        return response


def magic_link(request, token):
    """Validate a magic-link token, set cookie, and redirect to profile edit."""
    try:
        person = Person.objects.get(guest_token=token)
    except Person.DoesNotExist:
        messages.error(request, "That link is invalid or has already been used.")
        return redirect('guest_setup')

    response = redirect('profile_edit')
    response.set_cookie(
        GUEST_COOKIE_NAME,
        str(person.guest_token),
        max_age=GUEST_COOKIE_MAX_AGE,
        httponly=True,
        samesite='Lax',
    )
    return response


def profile_edit(request):
    """Display and handle the profile/preference edit form."""
    person = get_person_from_request(request)
    if person is None:
        return redirect('guest_setup')

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
            for topping in toppings:
                key = f'pref_{topping.pk}'
                val_str = request.POST.get(key)
                if val_str == 'allergy':
                    val = PersonToppingPreference.ALLERGY
                elif val_str == 'dislike':
                    val = PersonToppingPreference.DISLIKE
                elif val_str == 'neutral':
                    val = PersonToppingPreference.NEUTRAL
                elif val_str == 'like':
                    val = PersonToppingPreference.LIKE
                else:
                    val = None

                if val is not None:
                    PersonToppingPreference.objects.update_or_create(
                        person=person,
                        topping=topping,
                        defaults={'preference': val},
                    )
                else:
                    PersonToppingPreference.objects.filter(person=person, topping=topping).delete()

            messages.success(request, "Your preferences have been saved.")
            return redirect('profile_edit')
    else:
        form = PersonProfileForm(instance=person)

    return render(request, 'webapp/profile/edit.html', {
        'form': form,
        'toppings': toppings,
        'allergy_ids': allergy_ids,
        'dislike_ids': dislike_ids,
        'neutral_ids': neutral_ids,
        'like_ids': like_ids,
    })


@login_required
def create_order(request):
    """
    GET:  Display the order creation form.
    POST: Validate form, create Order, run solver, save results, redirect to results.
    """
    person, _ = Person.objects.get_or_create(
        user_account=request.user,
        defaults={'name': request.user.email, 'email': request.user.email},
    )

    if request.method == 'POST':
        form = CreateOrderForm(request.POST, host=person)
        if form.is_valid():
            data = form.cleaned_data

            # Create the Order
            order = Order.objects.create(
                host=person,
                vendor=data['vendor'],
                num_pizzas=data['num_pizzas'],
                optimization_mode=data['optimization_mode'],
            )
            order.people.set(set(data['people']) | {person})

            # Run the solver (saves pizzas and M2M relations internally)
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
                order.delete()
                return render(request, 'webapp/order_create.html', {'form': form, 'host': person})

            messages.success(request, "Pizza order generated successfully!")
            return redirect('order_results', order_id=order.id)
    else:
        form = CreateOrderForm(host=person)

    return render(request, 'webapp/order_create.html', {'form': form, 'host': person})


def order_results(request, order_id):
    """Display the results of a pizza order: pizzas, toppings, and assigned people."""
    order = get_object_or_404(
        Order.objects.select_related('host', 'vendor').prefetch_related('people', 'pizzas'),
        id=order_id,
    )
    pizzas = (
        order.pizzas
        .prefetch_related('toppings', 'people')
        .all()
    )
    return render(request, 'webapp/order_results.html', {
        'order': order,
        'pizzas': pizzas,
    })


# ---------------------------------------------------------------------------
# Topping CRUD
# ---------------------------------------------------------------------------

@login_required
def topping_list(request):
    toppings = Topping.objects.order_by(Lower('name'))
    return render(request, 'webapp/toppings/list.html', {'toppings': toppings})


@login_required
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
def topping_merge(request, pk):
    topping = get_object_or_404(Topping, pk=pk)

    if request.method == 'POST':
        form = MergeToppingForm(request.POST, exclude_pk=pk)
        if form.is_valid():
            target = form.cleaned_data['target']

            # PersonToppingPreference — skip if person already has a preference for target
            for pref in PersonToppingPreference.objects.filter(topping=topping):
                if PersonToppingPreference.objects.filter(person=pref.person, topping=target).exists():
                    pref.delete()
                else:
                    pref.topping = target
                    pref.save()

            # VendorTopping — skip if vendor already offers target
            for vt in VendorTopping.objects.filter(topping=topping):
                if VendorTopping.objects.filter(vendor=vt.vendor, topping=target).exists():
                    vt.delete()
                else:
                    vt.topping = target
                    vt.save()

            # OrderedPizza M2M fields
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
    topping = get_object_or_404(Topping, pk=pk)
    if request.method == 'POST':
        name = str(topping)
        topping.delete()
        messages.success(request, f"Topping '{name}' deleted.")
        return redirect('topping_list')
    return render(request, 'webapp/toppings/confirm_delete.html', {'topping': topping})


# ---------------------------------------------------------------------------
# Vendor CRUD
# ---------------------------------------------------------------------------

@login_required
def vendor_list(request):
    vendors = PizzaVendor.objects.prefetch_related('toppings').order_by('name')
    return render(request, 'webapp/vendors/list.html', {'vendors': vendors})


@login_required
def vendor_create(request):
    if request.method == 'POST':
        form = VendorForm(request.POST)
        if form.is_valid():
            vendor = form.save()
            for topping in form.cleaned_data['toppings']:
                VendorTopping.objects.create(vendor=vendor, topping=topping)
            messages.success(request, f"Vendor '{vendor}' created.")
            return redirect('vendor_list')
    else:
        form = VendorForm()
    return render(request, 'webapp/vendors/form.html', {'form': form, 'action': 'Create'})


@login_required
def vendor_edit(request, pk):
    vendor = get_object_or_404(PizzaVendor, pk=pk)
    if request.method == 'POST':
        form = VendorForm(request.POST, instance=vendor)
        if form.is_valid():
            vendor = form.save()
            selected = set(form.cleaned_data['toppings'])
            existing = set(vendor.toppings.all())
            VendorTopping.objects.filter(vendor=vendor, topping__in=existing - selected).delete()
            for topping in selected - existing:
                VendorTopping.objects.create(vendor=vendor, topping=topping)
            messages.success(request, f"Vendor '{vendor}' updated.")
            return redirect('vendor_list')
    else:
        form = VendorForm(instance=vendor)
    return render(request, 'webapp/vendors/form.html', {'form': form, 'action': 'Edit', 'vendor': vendor})


@login_required
def vendor_delete(request, pk):
    vendor = get_object_or_404(PizzaVendor, pk=pk)
    if request.method == 'POST':
        name = str(vendor)
        vendor.delete()
        messages.success(request, f"Vendor '{name}' deleted.")
        return redirect('vendor_list')
    return render(request, 'webapp/vendors/confirm_delete.html', {'vendor': vendor})


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
            vendors_created = 0
            vendors_existed = 0
            warnings = []

            for line in lines:
                if not line or line.startswith('#'):
                    continue
                if line == '[toppings]':
                    section = 'toppings'
                    continue
                if line == '[vendors]':
                    section = 'vendors'
                    continue

                if section == 'toppings':
                    _, created = Topping.objects.get_or_create(name=line)
                    if created:
                        toppings_created += 1
                    else:
                        toppings_existed += 1

                elif section == 'vendors':
                    if ':' in line:
                        vendor_name, topping_str = line.split(':', 1)
                        vendor_name = vendor_name.strip()
                        topping_names = [t.strip() for t in topping_str.split(',') if t.strip()]
                    else:
                        vendor_name = line
                        topping_names = []

                    if not vendor_name:
                        warnings.append(f"Could not parse vendor line: {line!r}")
                        continue

                    vendor, created = PizzaVendor.objects.get_or_create(name=vendor_name)
                    if created:
                        vendors_created += 1
                    else:
                        vendors_existed += 1

                    for topping_name in topping_names:
                        topping, t_created = Topping.objects.get_or_create(name=topping_name)
                        if t_created:
                            toppings_created += 1
                        VendorTopping.objects.get_or_create(vendor=vendor, topping=topping)

                else:
                    warnings.append(f"Line outside any section: {line!r}")

            context['results'] = {
                'toppings_created': toppings_created,
                'toppings_existed': toppings_existed,
                'vendors_created': vendors_created,
                'vendors_existed': vendors_existed,
            }
            context['warnings'] = warnings

    return render(request, 'webapp/import.html', context)
