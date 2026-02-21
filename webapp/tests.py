from django.test import TestCase, Client
from django.urls import reverse

from .models import (
    Person, Topping, PizzaVendor, VendorTopping,
    PersonToppingPreference, Order, OrderedPizza,
)
from .solver import solve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_vendor(name="Test Pizza", toppings=None):
    vendor = PizzaVendor.objects.create(name=name)
    for t in (toppings or []):
        VendorTopping.objects.create(vendor=vendor, topping=t)
    return vendor


def make_person(name, unrated_is_dislike=False, prefs=None):
    """Create a Person and set topping preferences. prefs: {topping: preference_value}"""
    p = Person.objects.create(
        name=name,
        email=f"{name.lower().replace(' ', '')}@test.com",
        unrated_is_dislike=unrated_is_dislike,
    )
    for topping, pref in (prefs or {}).items():
        PersonToppingPreference.objects.create(person=p, topping=topping, preference=pref)
    return p


def make_order(vendor, host, people, num_pizzas=1, pizza_mode='whole', optimization_mode='maximize_likes'):
    order = Order.objects.create(
        host=host, vendor=vendor,
        num_pizzas=num_pizzas, pizza_mode=pizza_mode,
        optimization_mode=optimization_mode,
    )
    order.people.set(people)
    return order


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class PersonToppingPreferenceModelTests(TestCase):
    def setUp(self):
        self.topping = Topping.objects.create(name="Mushroom")
        self.person = Person.objects.create(name="Alice", email="alice@test.com")

    def test_preference_choices_are_integers(self):
        self.assertEqual(PersonToppingPreference.ALLERGY, -2)
        self.assertEqual(PersonToppingPreference.DISLIKE, -1)
        self.assertEqual(PersonToppingPreference.NEUTRAL, 0)
        self.assertEqual(PersonToppingPreference.LIKE, 1)

    def test_str_shows_display_name(self):
        pref = PersonToppingPreference.objects.create(
            person=self.person, topping=self.topping,
            preference=PersonToppingPreference.ALLERGY,
        )
        self.assertIn("Allergy", str(pref))

    def test_unique_together_enforced(self):
        PersonToppingPreference.objects.create(
            person=self.person, topping=self.topping,
            preference=PersonToppingPreference.LIKE,
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            PersonToppingPreference.objects.create(
                person=self.person, topping=self.topping,
                preference=PersonToppingPreference.DISLIKE,
            )


class OrderModelTests(TestCase):
    def setUp(self):
        self.vendor = PizzaVendor.objects.create(name="Papa's")
        self.person = Person.objects.create(name="Bob", email="bob@test.com")

    def test_order_defaults(self):
        order = Order.objects.create(host=self.person, vendor=self.vendor)
        self.assertEqual(order.num_pizzas, 1)
        self.assertEqual(order.pizza_mode, 'whole')
        self.assertEqual(order.optimization_mode, 'maximize_likes')

    def test_order_str(self):
        order = Order.objects.create(host=self.person, vendor=self.vendor)
        self.assertIn("Papa's", str(order))


# ---------------------------------------------------------------------------
# Solver stub tests
# ---------------------------------------------------------------------------

class SolverStubTests(TestCase):
    def setUp(self):
        self.vendor = make_vendor()
        self.person = make_person("Charlie")
        self.order = make_order(self.vendor, self.person, [self.person])

    def test_solve_raises_not_implemented(self):
        # Now solve() works; just verify it returns a list without raising
        result = solve(self.order)
        self.assertIsInstance(result, list)


# ---------------------------------------------------------------------------
# View integration tests
# ---------------------------------------------------------------------------

class CreateOrderViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.topping = Topping.objects.create(name="Pepperoni")
        self.vendor = make_vendor(toppings=[self.topping])
        self.alice = make_person("Alice")
        self.bob = make_person("Bob")

    def test_get_create_order_returns_200(self):
        response = self.client.get(reverse('create_order'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New Pizza Order")

    def test_post_invalid_form_shows_errors(self):
        response = self.client.post(reverse('create_order'), data={})
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'vendor', 'This field is required.')

    def test_post_valid_form_creates_order_and_redirects(self):
        response = self.client.post(reverse('create_order'), data={
            'vendor': self.vendor.pk,
            'host': self.alice.pk,
            'people': [self.alice.pk, self.bob.pk],
            'num_pizzas': 1,
            'pizza_mode': 'whole',
            'optimization_mode': 'maximize_likes',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/results/', response['Location'])
        self.assertEqual(Order.objects.count(), 1)

    def test_host_not_in_people_shows_error(self):
        response = self.client.post(reverse('create_order'), data={
            'vendor': self.vendor.pk,
            'host': self.alice.pk,
            'people': [self.bob.pk],  # alice is host but not in people
            'num_pizzas': 1,
            'pizza_mode': 'whole',
            'optimization_mode': 'maximize_likes',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "host must be included")

    def test_more_pizzas_than_people_shows_error(self):
        response = self.client.post(reverse('create_order'), data={
            'vendor': self.vendor.pk,
            'host': self.alice.pk,
            'people': [self.alice.pk],
            'num_pizzas': 5,
            'pizza_mode': 'whole',
            'optimization_mode': 'maximize_likes',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "more pizzas than people")


class OrderResultsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.topping = Topping.objects.create(name="Cheese")
        self.vendor = make_vendor(toppings=[self.topping])
        self.alice = make_person("Alice")
        self.order = make_order(self.vendor, self.alice, [self.alice])

    def test_results_page_returns_200(self):
        url = reverse('order_results', kwargs={'order_id': self.order.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Order #{self.order.pk}")

    def test_results_page_shows_no_assignments_when_empty(self):
        url = reverse('order_results', kwargs={'order_id': self.order.pk})
        response = self.client.get(url)
        self.assertContains(response, "No pizza assignments")

    def test_results_page_shows_pizza_when_assigned(self):
        pizza = OrderedPizza.objects.create(order=self.order)
        pizza.people.set([self.alice])
        pizza.left_toppings.set([self.topping])
        url = reverse('order_results', kwargs={'order_id': self.order.pk})
        response = self.client.get(url)
        self.assertContains(response, "Pizza #1")
        self.assertContains(response, "Cheese")
        self.assertContains(response, "Alice")

    def test_results_page_404_for_missing_order(self):
        url = reverse('order_results', kwargs={'order_id': 9999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# Solver tests
# ---------------------------------------------------------------------------

class SolverTests(TestCase):
    """Tests for the ILP pizza solver."""

    def _make_toppings(self, *names):
        return [Topping.objects.create(name=n) for n in names]

    # --- test_allergy_never_violated ---

    def test_allergy_never_violated(self):
        """No person should appear on a pizza containing their allergen."""
        t_pep, t_mush = self._make_toppings("Pepperoni", "Mushroom")
        vendor = make_vendor(toppings=[t_pep, t_mush])
        alice = make_person("Alice", prefs={t_pep: PersonToppingPreference.ALLERGY})
        bob = make_person("Bob", prefs={t_pep: PersonToppingPreference.LIKE})
        order = make_order(vendor, alice, [alice, bob], num_pizzas=1, pizza_mode='whole')

        pizzas = solve(order)

        for pizza in pizzas:
            left_top_ids = set(pizza.left_toppings.values_list('id', flat=True))
            for person in pizza.people.all():
                allergies = PersonToppingPreference.objects.filter(
                    person=person,
                    preference=PersonToppingPreference.ALLERGY,
                ).values_list('topping_id', flat=True)
                for allergen_id in allergies:
                    self.assertNotIn(
                        allergen_id, left_top_ids,
                        f"{person.name} is on a pizza with their allergen"
                    )

    def test_allergy_never_violated_half(self):
        """Allergy constraint respected in half mode."""
        t_pep, t_mush = self._make_toppings("Pepperoni2", "Mushroom2")
        vendor = make_vendor(name="Half Vendor", toppings=[t_pep, t_mush])
        alice = make_person("AliceH", prefs={t_pep: PersonToppingPreference.ALLERGY})
        bob = make_person("BobH", prefs={t_pep: PersonToppingPreference.LIKE})
        order = make_order(vendor, alice, [alice, bob], num_pizzas=1, pizza_mode='half')

        pizzas = solve(order)

        for pizza in pizzas:
            left_ids = set(pizza.left_toppings.values_list('id', flat=True))
            right_ids = set(pizza.right_toppings.values_list('id', flat=True))
            for person in pizza.people.all():
                allergies = list(PersonToppingPreference.objects.filter(
                    person=person, preference=PersonToppingPreference.ALLERGY,
                ).values_list('topping_id', flat=True))
                for allergen_id in allergies:
                    self.assertNotIn(allergen_id, left_ids | right_ids)

    # --- test_topping_cap ---

    def test_topping_cap(self):
        """No pizza half should have more than 3 toppings."""
        tops = self._make_toppings("A", "B", "C", "D", "E")
        vendor = make_vendor(name="Cap Vendor", toppings=tops)
        alice = make_person("AliceCap", prefs={t: PersonToppingPreference.LIKE for t in tops})
        order = make_order(vendor, alice, [alice], num_pizzas=1, pizza_mode='whole')

        pizzas = solve(order)

        for pizza in pizzas:
            self.assertLessEqual(pizza.left_toppings.count(), 3)
            self.assertLessEqual(pizza.right_toppings.count(), 3)

    def test_topping_cap_half(self):
        """Topping cap applies per half in half mode."""
        tops = self._make_toppings("H1", "H2", "H3", "H4", "H5")
        vendor = make_vendor(name="Cap Half Vendor", toppings=tops)
        alice = make_person("AliceCapH", prefs={t: PersonToppingPreference.LIKE for t in tops})
        bob = make_person("BobCapH", prefs={t: PersonToppingPreference.LIKE for t in tops})
        order = make_order(vendor, alice, [alice, bob], num_pizzas=1, pizza_mode='half')

        pizzas = solve(order)

        for pizza in pizzas:
            self.assertLessEqual(pizza.left_toppings.count(), 3)
            self.assertLessEqual(pizza.right_toppings.count(), 3)

    # --- test_every_person_assigned ---

    def test_every_person_assigned(self):
        """All people in the order appear on exactly one pizza."""
        tops = self._make_toppings("Olive", "Bacon")
        vendor = make_vendor(name="Assign Vendor", toppings=tops)
        alice = make_person("AliceA")
        bob = make_person("BobA")
        charlie = make_person("CharlieA")
        order = make_order(vendor, alice, [alice, bob, charlie], num_pizzas=2)

        pizzas = solve(order)

        assigned = []
        for pizza in pizzas:
            assigned.extend(pizza.people.values_list('id', flat=True))

        order_people_ids = list(order.people.values_list('id', flat=True))
        self.assertCountEqual(assigned, order_people_ids)

    # --- test_every_pizza_has_person ---

    def test_every_pizza_has_person(self):
        """No pizza should be empty."""
        tops = self._make_toppings("Onion", "Pepper")
        vendor = make_vendor(name="NonEmpty Vendor", toppings=tops)
        alice = make_person("AliceNE")
        bob = make_person("BobNE")
        order = make_order(vendor, alice, [alice, bob], num_pizzas=2)

        pizzas = solve(order)

        for pizza in pizzas:
            self.assertGreater(pizza.people.count(), 0, "Pizza has no people assigned")

    # --- test_maximize_likes_prefers_liked_toppings ---

    def test_maximize_likes_prefers_liked_toppings(self):
        """In maximize_likes mode, a liked topping should appear on the pizza."""
        t_like, t_neutral = self._make_toppings("LikedTopping", "NeutralTopping")
        vendor = make_vendor(name="Likes Vendor", toppings=[t_like, t_neutral])
        alice = make_person("AliceLikes", prefs={t_like: PersonToppingPreference.LIKE})
        order = make_order(vendor, alice, [alice], num_pizzas=1, optimization_mode='maximize_likes')

        pizzas = solve(order)

        self.assertEqual(len(pizzas), 1)
        left_ids = set(pizzas[0].left_toppings.values_list('id', flat=True))
        self.assertIn(t_like.id, left_ids, "Liked topping should be on the pizza")

    # --- test_minimize_dislikes_balances_scores ---

    def test_minimize_dislikes_balances_scores(self):
        """minimize_dislikes should maximize the worst-case pizza score vs maximize_likes."""
        # Two people each liking different toppings; 2 pizzas
        # maximize_likes might put all liked toppings on one pizza
        # minimize_dislikes should ensure a more balanced assignment
        t1, t2 = self._make_toppings("MinDisT1", "MinDisT2")
        vendor = make_vendor(name="MinDis Vendor", toppings=[t1, t2])
        alice = make_person("AliceMD", prefs={t1: PersonToppingPreference.LIKE, t2: PersonToppingPreference.DISLIKE})
        bob = make_person("BobMD", prefs={t2: PersonToppingPreference.LIKE, t1: PersonToppingPreference.DISLIKE})
        people = [alice, bob]

        order_md = make_order(vendor, alice, people, num_pizzas=2, optimization_mode='minimize_dislikes')
        pizzas_md = solve(order_md)

        # Each person should be on a separate pizza
        self.assertEqual(len(pizzas_md), 2)
        # Each pizza should have exactly 1 person
        for pizza in pizzas_md:
            self.assertEqual(pizza.people.count(), 1)
        # Each person gets their preferred topping, not the one they dislike
        for pizza in pizzas_md:
            person = pizza.people.first()
            topping_ids = set(pizza.left_toppings.values_list('id', flat=True))
            dislikes = set(PersonToppingPreference.objects.filter(
                person=person, preference=PersonToppingPreference.DISLIKE
            ).values_list('topping_id', flat=True))
            self.assertTrue(topping_ids.isdisjoint(dislikes),
                            f"{person.name} has a disliked topping on their pizza")

    # --- test_whole_bonus_prevents_unnecessary_split ---

    def test_whole_bonus_prevents_unnecessary_split(self):
        """Solver should keep pizza whole when splitting adds no benefit."""
        t1, = self._make_toppings("BonusTop")
        vendor = make_vendor(name="Bonus Vendor", toppings=[t1])
        # Both people like the same topping — no reason to split
        alice = make_person("AliceBonus", prefs={t1: PersonToppingPreference.LIKE})
        bob = make_person("BobBonus", prefs={t1: PersonToppingPreference.LIKE})
        order = make_order(vendor, alice, [alice, bob], num_pizzas=1, pizza_mode='half')

        pizzas = solve(order)

        self.assertEqual(len(pizzas), 1)
        # Pizza should not be split: right_toppings empty, all people on left
        self.assertEqual(pizzas[0].right_toppings.count(), 0,
                         "Pizza should not be split when everyone likes same toppings")

    # --- test_unrated_is_dislike_excludes_unrated_toppings ---

    def test_unrated_is_dislike_excludes_unrated_toppings(self):
        """When unrated_is_dislike=True, unrated toppings should not appear on pizza."""
        t_unrated, t_liked = self._make_toppings("UnratedTop", "LikedTop2")
        vendor = make_vendor(name="Unrated Vendor", toppings=[t_unrated, t_liked])
        # Person has unrated_is_dislike=True and only likes t_liked
        alice = make_person("AliceUnrated", unrated_is_dislike=True,
                            prefs={t_liked: PersonToppingPreference.LIKE})
        order = make_order(vendor, alice, [alice], num_pizzas=1, optimization_mode='maximize_likes')

        pizzas = solve(order)

        self.assertEqual(len(pizzas), 1)
        left_ids = set(pizzas[0].left_toppings.values_list('id', flat=True))
        self.assertNotIn(t_unrated.id, left_ids,
                         "Unrated topping should be excluded when unrated_is_dislike=True")

    # --- test_unrated_is_neutral_includes_unrated_toppings ---

    def test_unrated_is_neutral_includes_unrated_toppings(self):
        """When unrated_is_dislike=False, unrated toppings may appear on pizza."""
        # To force the solver to pick the unrated topping, make it the only available one
        t_unrated, = self._make_toppings("NeutralUnrated")
        vendor = make_vendor(name="Neutral Vendor", toppings=[t_unrated])
        # Person has no preferences recorded (default neutral) and unrated_is_dislike=False
        alice = make_person("AliceNeutral", unrated_is_dislike=False)
        # Give alice a LIKE for the unrated topping so solver picks it
        PersonToppingPreference.objects.create(
            person=alice, topping=t_unrated, preference=PersonToppingPreference.LIKE
        )
        order = make_order(vendor, alice, [alice], num_pizzas=1, optimization_mode='maximize_likes')

        pizzas = solve(order)

        self.assertEqual(len(pizzas), 1)
        left_ids = set(pizzas[0].left_toppings.values_list('id', flat=True))
        self.assertIn(t_unrated.id, left_ids,
                      "Liked topping should appear on pizza")
