"""
Management command to seed the database with test users and sample preference data.

Usage:
    python manage.py seed_test_data

Wipes all non-superuser accounts and non-topping data, then creates 27 test users
(Person01–Person27) with password 'testpass', along with a group, a restaurant, and
topping preferences sourced from a real group preference survey.

Toppings are created via get_or_create so this command works whether or not
seed_toppings has been run first.
"""

from django.core.management.base import BaseCommand

from webapp.models import (
    GroupMembership, Order, OrderedPizza, Person, PersonToppingPreference,
    PizzaGroup, PizzaRestaurant, Topping, User, RestaurantTopping,
)

PEOPLE = [
    "Person01", "Person02", "Person03", "Person04", "Person05", "Person06", "Person07",
    "Person08", "Person09", "Person10", "Person11", "Person12", "Person13", "Person14",
    "Person15", "Person16", "Person17", "Person18", "Person19", "Person20", "Person21",
    "Person22", "Person23", "Person24", "Person25", "Person26", "Person27",
]

# Each list has 27 values, one per person above.
PREFERENCES = {
    # Meats
    "Bacon":            [-1,-2, 0,-2,-2,-1, 0, 1, 0,-1,-1, 0,-1, 1, 1,-2, 0,-1, 0, 1, 0, 0,-2, 1,-1, 1,-1],
    "Buffalo Chicken":  [ 0, 1, 1,-2,-2,-1, 0,-1, 1, 0, 0,-1,-2, 1, 1, 0, 0,-1, 0, 1, 0,-1,-2, 0, 0, 1, 0],
    "Chicken":          [ 0, 1, 0,-2,-2,-1, 0, 1, 0, 1, 0, 0, 0, 1, 1, 0, 1, 0, 0, 1, 0, 0,-2, 0, 0, 1, 0],
    "Meatballs":        [ 1, 1,-1,-2,-2,-1, 0, 0, 0, 0, 0, 0, 0, 1, 1,-1, 1, 1, 0, 1, 1, 0,-2, 0, 0, 1, 0],
    "Pepperoni":        [ 0,-2, 1,-2,-2,-1, 0,-1, 0, 0, 0, 0, 0, 1, 1,-2, 1,-1, 0, 1, 1, 1,-2, 0, 0, 1, 1],
    "Sausage":          [ 1, 1, 1,-2,-2,-1, 0,-2, 0, 1, 0, 0, 0, 1,-2,-1, 1, 1, 0, 1, 1, 1,-2, 0, 0, 1, 1],
    # Vegetables / Fruit
    "Artichoke":        [ 1, 1,-2, 1, 0, 1, 0, 0,-1,-2, 1, 1,-1, 0,-2,-1, 0, 1, 0, 1, 0,-1,-1,-1, 0, 1, 0],
    "Basil":            [ 1, 1,-1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 1],
    "Black Olives":     [ 1, 1,-2,-1, 1, 0, 1,-2, 1,-2, 1, 0, 0, 0, 0,-1, 1, 1,-1,-1,-2,-1,-1,-1, 0,-1,-1],
    "Broccoli":         [ 1, 1,-2, 1,-1, 1, 1, 1, 0, 1, 0, 0, 0, 0,-2, 0, 1,-1, 1,-1, 0,-1, 1, 0, 0, 0, 1],
    "Fried Eggplant":   [ 1, 1,-1, 1, 1, 0, 0, 0, 0, 0,-1, 1,-1, 0,-2, 0, 1,-1, 0, 0, 0,-1,-1, 0, 0, 1,-1],
    "Garlic":           [ 0, 1, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0],
    "Green Olives":     [ 0, 1,-2,-1,-1, 0, 1,-2, 1,-1, 0, 0, 0, 0, 0,-1, 0, 1, 0, 1,-2,-1,-1,-1,-1,-1,-1],
    "Green Peppers":    [ 0, 1, 0, 1, 1, 1, 1, 0, 1, 1,-2, 0, 0, 0, 0, 0, 1, 1, 0, 1,-2, 1, 1, 0, 1,-1, 1],
    "Mushrooms":        [ 1, 1, 1, 1,-2, 1, 1,-2, 1, 1, 0, 0, 1, 0, 1, 1, 1,-1, 1, 1, 1, 1, 0, 1, 1, 1, 0],
    "Onions":           [-1, 1, 1, 1, 1, 1, 1, 1, 0,-2, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 1, 1,-1, 0, 0, 1],
    "Pineapple":        [ 0, 1, 1, 0, 1, 0, 1,-2, 1, 1,-1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1,-2,-1, 1, 1, 1,-1],
    "Red Onion":        [ 0, 1, 1, 1, 0, 1, 1, 0, 0,-2, 1, 0, 0, 0, 1, 1,-1, 1, 1, 1, 0, 1, 0, 0, 1, 0, 1],
    "Spinach":          [ 1, 1,-2, 1, 1, 1, 1, 1, 0, 0, 1, 0, 0, 0,-2, 1, 1, 1, 1, 0, 0, 0, 1, 1, 0, 1, 1],
    "Sun Dried Tomatoes":[ 1, 1,-2, 0, 0, 1, 1, 1, 0,-1, 1, 1, 0, 0,-2,-2,-2, 1, 1, 1, 0, 0,-1, 1, 0, 0, 0],
}

RESTAURANT_NAME = "Mario's Pizza"
GROUP_NAME = "Survey Group"
TEST_PASSWORD = "testpass"


class Command(BaseCommand):
    help = "Wipe non-superuser accounts and non-topping data, then seed with test users and sample preferences."

    def handle(self, *args, **options):
        self._wipe()
        toppings = self._ensure_toppings()
        people = self._create_people(toppings)
        group = self._create_group(people)
        self._create_restaurant(toppings, group)
        self.stdout.write(self.style.SUCCESS("Test data seeding complete."))

    def _wipe(self):
        OrderedPizza.objects.all().delete()
        Order.objects.all().delete()
        PersonToppingPreference.objects.all().delete()
        GroupMembership.objects.all().delete()
        PizzaGroup.objects.all().delete()
        RestaurantTopping.objects.all().delete()
        Person.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()
        PizzaRestaurant.objects.all().delete()
        self.stdout.write("  Wiped all non-superuser, non-topping data.")

    def _ensure_toppings(self):
        toppings = {}
        for name in PREFERENCES:
            topping, _ = Topping.objects.get_or_create(name=name)
            toppings[name] = topping
        self.stdout.write(f"  Ensured {len(toppings)} toppings exist.")
        return toppings

    def _create_people(self, toppings):
        PREF = PersonToppingPreference
        topping_names = list(PREFERENCES.keys())
        people = []

        for p_idx, name in enumerate(PEOPLE):
            email = f"{name.lower()}@example.com"
            user = User.objects.create(username=email, email=email)
            user.set_password(TEST_PASSWORD)
            user.save()

            person = Person.objects.create(name=name, email=email, user_account=user)
            bulk = [
                PREF(
                    person=person,
                    topping=toppings[topping_name],
                    preference=PREFERENCES[topping_name][p_idx],
                )
                for topping_name in topping_names
            ]
            PREF.objects.bulk_create(bulk)
            people.append(person)

        self.stdout.write(f"  Created {len(PEOPLE)} users (password: '{TEST_PASSWORD}') with preferences.")
        return people

    def _create_group(self, people):
        group = PizzaGroup.objects.create(name=GROUP_NAME)
        GroupMembership.objects.bulk_create([
            GroupMembership(group=group, person=person, is_admin=(i == 0))
            for i, person in enumerate(people)
        ])
        self.stdout.write(f"  Created group '{GROUP_NAME}' with {len(people)} members.")
        return group

    def _create_restaurant(self, toppings, group):
        restaurant = PizzaRestaurant.objects.create(name=RESTAURANT_NAME, group=group)
        RestaurantTopping.objects.bulk_create([
            RestaurantTopping(restaurant=restaurant, topping=topping)
            for topping in toppings.values()
        ])
        self.stdout.write(f"  Created restaurant '{RESTAURANT_NAME}' with {len(toppings)} toppings.")
        return restaurant
