from django import forms
from django.forms import CheckboxSelectMultiple, ModelMultipleChoiceField
from .models import Order, Person, PizzaGroup, PizzaRestaurant, Topping


class CreateOrderForm(forms.Form):
    group = forms.ModelChoiceField(
        queryset=PizzaGroup.objects.none(),
        label="Group",
        empty_label="-- Select a group --",
    )
    restaurant = forms.ModelChoiceField(
        queryset=PizzaRestaurant.objects.all(),
        label="Restaurant",
        empty_label="-- Select a restaurant --",
    )
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
        initial='maximize_likes',
    )

    def __init__(self, *args, host=None, selected_group=None, proto_order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.host = host
        self._guest_pks = set()
        if host is not None:
            self.fields['group'].queryset = host.pizza_groups.all()

        if selected_group is not None:
            self.fields['group'].widget = forms.HiddenInput()
            self.fields['group'].initial = selected_group.pk

            if proto_order is not None:
                self.fields['restaurant'].queryset = PizzaRestaurant.objects.filter(pk=proto_order.restaurant.pk)
                self.fields['restaurant'].widget = forms.HiddenInput()
                guest_persons = proto_order.guest_persons.all()
                self._guest_pks = set(guest_persons.values_list('pk', flat=True))
                group_members_excl_host = (
                    selected_group.members.exclude(pk=host.pk) if host else selected_group.members.all()
                )
                self.fields['people'].queryset = (group_members_excl_host | guest_persons).distinct()
            else:
                self.fields['people'].queryset = (
                    selected_group.members.exclude(pk=host.pk) if host else selected_group.members.all()
                )
                self.fields['restaurant'].queryset = PizzaRestaurant.objects.filter(group=selected_group)

    def clean(self):
        cleaned = super().clean()
        group = cleaned.get('group')
        people = cleaned.get('people')
        num_pizzas = cleaned.get('num_pizzas')

        if group and people is not None:
            group_member_ids = set(group.members.values_list('pk', flat=True))
            for person in people:
                if person.pk not in group_member_ids and person.pk not in self._guest_pks:
                    self.add_error('people', f"{person.name} is not a member of the selected group.")

        if num_pizzas and people is not None and self.host:
            effective_count = len(set(people) | {self.host})
            if num_pizzas > effective_count:
                self.add_error('num_pizzas', "Cannot have more pizzas than people.")

        return cleaned


class ImportForm(forms.Form):
    file = forms.FileField(label="Import file (.txt)")


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


