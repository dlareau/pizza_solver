from django import forms
from .models import Order, Person, PizzaVendor


class CreateOrderForm(forms.Form):
    vendor = forms.ModelChoiceField(
        queryset=PizzaVendor.objects.all(),
        label="Pizza Vendor",
        empty_label="-- Select a vendor --",
    )
    host = forms.ModelChoiceField(
        queryset=Person.objects.all(),
        label="Host (your name)",
        empty_label="-- Select host --",
    )
    people = forms.ModelMultipleChoiceField(
        queryset=Person.objects.all(),
        label="People in this order",
        widget=forms.CheckboxSelectMultiple,
    )
    num_pizzas = forms.IntegerField(
        min_value=1,
        label="Number of pizzas",
        initial=1,
    )
    pizza_mode = forms.ChoiceField(
        choices=Order.PIZZA_MODE_CHOICES,
        label="Pizza mode",
        initial='whole',
    )
    optimization_mode = forms.ChoiceField(
        choices=Order.OPTIMIZATION_MODE_CHOICES,
        label="Optimization strategy",
        initial='maximize_likes',
    )

    def clean(self):
        cleaned = super().clean()
        host = cleaned.get('host')
        people = cleaned.get('people')
        num_pizzas = cleaned.get('num_pizzas')

        if host and people is not None and host not in people:
            self.add_error('people', "The host must be included in the list of people.")

        if num_pizzas and people is not None and num_pizzas > len(people):
            self.add_error('num_pizzas', "Cannot have more pizzas than people.")

        return cleaned
