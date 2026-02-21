from django import forms
from django.forms import CheckboxSelectMultiple, ModelMultipleChoiceField
from .models import Order, Person, PizzaVendor, Topping


class CreateOrderForm(forms.Form):
    vendor = forms.ModelChoiceField(
        queryset=PizzaVendor.objects.all(),
        label="Pizza Vendor",
        empty_label="-- Select a vendor --",
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

    def __init__(self, *args, host=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.host = host

    def clean(self):
        cleaned = super().clean()
        people = cleaned.get('people')
        num_pizzas = cleaned.get('num_pizzas')

        if num_pizzas and people is not None and self.host:
            effective_count = len(set(people) | {self.host})
            if num_pizzas > effective_count:
                self.add_error('num_pizzas', "Cannot have more pizzas than people.")

        return cleaned


class ToppingForm(forms.ModelForm):
    class Meta:
        model = Topping
        fields = ['name']


class VendorForm(forms.ModelForm):
    toppings = ModelMultipleChoiceField(
        queryset=Topping.objects.all(),
        required=False,
        widget=CheckboxSelectMultiple,
    )

    class Meta:
        model = PizzaVendor
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['toppings'].initial = self.instance.toppings.values_list('pk', flat=True)
