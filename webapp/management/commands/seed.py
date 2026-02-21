"""
Management command to seed the database with test data.

Usage:
    python manage.py seed

Wipes all non-user tables, then seeds one vendor, 27 anonymized people,
and their topping preferences (meats + vegetables only) imported from the
group preference survey.

Preference scale: LIKE=1, NEUTRAL=0, DISLIKE=-1, ALLERGY=-2.
Survey values of -3 and -2 are both mapped to ALLERGY.
"""

from django.core.management.base import BaseCommand

from webapp.models import (
    Order, OrderedPizza, Person, PersonToppingPreference,
    PizzaVendor, Topping, VendorTopping,
)

# ---------------------------------------------------------------------------
# Hardcoded survey data (meats + veggies; sauces and cheeses excluded)
# 27 people, anonymized as Person01–Person27.
# Mapping applied: -3 → -2 (ALLERGY), -2 → -2, -1 → -1, 0 → 0, 1 → 1.
# ---------------------------------------------------------------------------

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

VENDOR_NAME = "Mario's Pizza"


class Command(BaseCommand):
    help = "Wipe non-user tables and seed with survey preference data."

    def handle(self, *args, **options):
        self._wipe()
        toppings = self._create_toppings()
        vendor = self._create_vendor(toppings)
        self._create_people(toppings)
        self.stdout.write(self.style.SUCCESS("Seeding complete."))

    def _wipe(self):
        OrderedPizza.objects.all().delete()
        Order.objects.all().delete()
        PersonToppingPreference.objects.all().delete()
        VendorTopping.objects.all().delete()
        Person.objects.all().delete()
        PizzaVendor.objects.all().delete()
        Topping.objects.all().delete()
        self.stdout.write("  Wiped all non-user tables.")

    def _create_toppings(self):
        toppings = {}
        for name in PREFERENCES:
            t = Topping.objects.create(name=name)
            toppings[name] = t
        self.stdout.write(f"  Created {len(toppings)} toppings.")
        return toppings

    def _create_vendor(self, toppings):
        vendor = PizzaVendor.objects.create(name=VENDOR_NAME)
        for topping in toppings.values():
            VendorTopping.objects.create(vendor=vendor, topping=topping)
        self.stdout.write(f"  Created vendor: {VENDOR_NAME}")
        return vendor

    def _create_people(self, toppings):
        PREF = PersonToppingPreference
        topping_names = list(PREFERENCES.keys())

        for p_idx, name in enumerate(PEOPLE):
            person = Person.objects.create(
                name=name,
                email=f"{name.lower()}@example.com",
            )
            bulk = []
            for topping_name in topping_names:
                value = PREFERENCES[topping_name][p_idx]
                if value != 0:  # skip neutrals
                    bulk.append(PREF(
                        person=person,
                        topping=toppings[topping_name],
                        preference=value,
                    ))
            PREF.objects.bulk_create(bulk)

        self.stdout.write(f"  Created {len(PEOPLE)} people with preferences.")
