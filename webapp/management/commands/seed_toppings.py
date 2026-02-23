"""
Management command to seed the toppings table with common pizza toppings.

Usage:
    python manage.py seed_toppings

Wipes the Topping table (cascading to VendorTopping and PersonToppingPreference)
and inserts a standard list of common pizza toppings.
"""

from django.core.management.base import BaseCommand

from webapp.models import PersonToppingPreference, Topping, VendorTopping


TOPPINGS = [
    # Meats
    "Anchovies",
    "Bacon",
    "Buffalo Chicken",
    "Chicken",
    "Chorizo",
    "Ground Beef",
    "Ham",
    "Meatballs",
    "Pepperoni",
    "Salami",
    "Sausage",
    "Steak",
    # Vegetables & Fruit
    "Artichokes",
    "Banana Peppers",
    "Basil",
    "Black Olives",
    "Broccoli",
    "Fried Eggplant",
    "Garlic",
    "Green Olives",
    "Green Peppers",
    "Jalapeños",
    "Mushrooms",
    "Onions",
    "Pineapple",
    "Red Onions",
    "Roasted Red Peppers",
    "Spinach",
    "Sun Dried Tomatoes",
    "Tomatoes",
    # Extras
    "Feta Cheese",
    "Extra Cheese",
    "Ricotta",
]


class Command(BaseCommand):
    help = "Wipe the toppings table and seed with common pizza toppings."

    def handle(self, *args, **options):
        PersonToppingPreference.objects.all().delete()
        VendorTopping.objects.all().delete()
        Topping.objects.all().delete()
        self.stdout.write("  Wiped toppings and related preferences.")

        Topping.objects.bulk_create([Topping(name=name) for name in TOPPINGS])
        self.stdout.write(self.style.SUCCESS(f"  Created {len(TOPPINGS)} toppings."))
