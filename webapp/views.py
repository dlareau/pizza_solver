from django.contrib.auth.decorators import login_required
from django.db.models.functions import Lower
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from .forms import CreateOrderForm, ToppingForm, VendorForm
from .models import Order, Person, Topping, PizzaVendor, VendorTopping
from .solver import solve


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
                pizza_mode=data['pizza_mode'],
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
        .prefetch_related('left_toppings', 'right_toppings', 'people')
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
