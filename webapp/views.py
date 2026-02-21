from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from .forms import CreateOrderForm
from .models import Order
from .solver import solve


def create_order(request):
    """
    GET:  Display the order creation form.
    POST: Validate form, create Order, run solver, save results, redirect to results.
    """
    if request.method == 'POST':
        form = CreateOrderForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data

            # Create the Order
            order = Order.objects.create(
                host=data['host'],
                vendor=data['vendor'],
                num_pizzas=data['num_pizzas'],
                pizza_mode=data['pizza_mode'],
                optimization_mode=data['optimization_mode'],
            )
            order.people.set(data['people'])

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
                return render(request, 'webapp/order_create.html', {'form': form})

            messages.success(request, "Pizza order generated successfully!")
            return redirect('order_results', order_id=order.id)
    else:
        form = CreateOrderForm()

    return render(request, 'webapp/order_create.html', {'form': form})


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
