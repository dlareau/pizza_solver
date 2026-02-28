from django import forms
from django.forms import CheckboxSelectMultiple, ModelMultipleChoiceField
from .models import Order, Person, PizzaGroup, PizzaRestaurant, Topping


class BaseOrderForm(forms.Form):
    people = forms.ModelMultipleChoiceField(
        queryset=Person.objects.none(),
        label="Select people for this order",
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    num_pizzas = forms.IntegerField(
        min_value=1,
        label="Number of pizzas",
        initial=1,
    )
    optimization_mode = forms.ChoiceField(
        choices=Order.OPTIMIZATION_MODE_CHOICES,
        label="Optimization strategy",
        initial='minimize_dislikes',
        widget=forms.HiddenInput(),
    )

    def __init__(self, *args, host=None, selected_group=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.host = host
        self.selected_group = selected_group
        self._guest_pks = set()

    def clean(self):
        cleaned = super().clean()
        people = cleaned.get('people')
        num_pizzas = cleaned.get('num_pizzas')

        if self.selected_group and people is not None:
            group_member_ids = set(self.selected_group.members.values_list('pk', flat=True))
            for person in people:
                if person.pk not in group_member_ids and person.pk not in self._guest_pks:
                    self.add_error('people', f"{person.name} is not a member of the selected group.")

        if num_pizzas and people is not None and self.host:
            effective_count = len(set(people) | {self.host})
            if num_pizzas > effective_count:
                self.add_error('num_pizzas', "Cannot have more pizzas than people.")

        return cleaned


class NewOrderForm(BaseOrderForm):
    restaurant = forms.ModelChoiceField(
        queryset=PizzaRestaurant.objects.order_by('name'),
        label="Restaurant",
        empty_label="-- Select a restaurant --",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['people'].queryset = (
            self.selected_group.members.exclude(pk=self.host.pk)
            if self.host else self.selected_group.members.all()
        )
        self.fields['restaurant'].queryset = PizzaRestaurant.objects.filter(
            group=self.selected_group
        ).order_by('name')


class DraftOrderForm(BaseOrderForm):
    def __init__(self, *args, proto_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        guest_persons = proto_order.guest_persons.all()
        self._guest_pks = set(guest_persons.values_list('pk', flat=True))
        group_members_excl_host = (
            self.selected_group.members.exclude(pk=self.host.pk)
            if self.host else self.selected_group.members.all()
        )
        self.fields['people'].queryset = (group_members_excl_host | guest_persons).distinct()


class MergeToppingForm(forms.Form):
    target = forms.ModelChoiceField(
        queryset=Topping.objects.none(),
        label="Merge into",
        empty_label="-- Select target topping --",
    )

    def __init__(self, *args, exclude_pk=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Topping.objects.order_by('name')
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        self.fields['target'].queryset = qs


class PersonProfileForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ['name', 'email', 'unrated_is_dislike']
        labels = {
            'unrated_is_dislike': 'Treat unrated toppings as dislikes',
        }


class ToppingForm(forms.ModelForm):
    class Meta:
        model = Topping
        fields = ['name']


class RestaurantForm(forms.ModelForm):
    toppings = ModelMultipleChoiceField(
        queryset=Topping.objects.order_by('name'),
        required=False,
        widget=CheckboxSelectMultiple,
    )

    class Meta:
        model = PizzaRestaurant
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['toppings'].initial = self.instance.toppings.values_list('pk', flat=True)


class PizzaGroupForm(forms.ModelForm):
    class Meta:
        model = PizzaGroup
        fields = ['name']



class GuestPreferenceForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ['name', 'unrated_is_dislike']


