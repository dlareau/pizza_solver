from django.test import TestCase, Client
from django.urls import reverse

from .models import (
    GroupMembership, Person, PizzaGroup, Topping, PizzaRestaurant, RestaurantTopping,
    PersonToppingPreference, Order, OrderedPizza,
)
from .solver import solve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_group(name="Test Group"):
    return PizzaGroup.objects.create(name=name)


def make_restaurant(name="Test Pizza", toppings=None, group=None):
    restaurant = PizzaRestaurant.objects.create(name=name, group=group)
    for t in (toppings or []):
        RestaurantTopping.objects.create(restaurant=restaurant, topping=t)
    return restaurant


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


def make_order(restaurant, host, people, num_pizzas=1, optimization_mode='maximize_likes',
               group=None, shareability_bonus_weight=0):
    if group is None:
        group = make_group()
    order = Order.objects.create(
        host=host, restaurant=restaurant,
        num_pizzas=num_pizzas,
        optimization_mode=optimization_mode,
        shareability_bonus_weight=shareability_bonus_weight,
        group=group,
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
        self.group = make_group("Papa's Group")
        self.restaurant = PizzaRestaurant.objects.create(name="Papa's", group=self.group)
        self.person = Person.objects.create(name="Bob", email="bob@test.com")

    def test_order_defaults(self):
        order = Order.objects.create(host=self.person, restaurant=self.restaurant, group=self.group)
        self.assertEqual(order.num_pizzas, 1)
        self.assertEqual(order.optimization_mode, 'minimize_dislikes')
        self.assertEqual(order.shareability_bonus_weight, 0)

    def test_order_str(self):
        order = Order.objects.create(host=self.person, restaurant=self.restaurant, group=self.group)
        self.assertIn("Papa's", str(order))


# ---------------------------------------------------------------------------
# Solver stub tests
# ---------------------------------------------------------------------------

class SolverStubTests(TestCase):
    def setUp(self):
        self.group = make_group()
        self.restaurant = make_restaurant(group=self.group)
        self.person = make_person("Charlie")
        self.order = make_order(self.restaurant, self.person, [self.person], group=self.group)

    def test_solve_raises_not_implemented(self):
        # Now solve() works; just verify it returns a list without raising
        result = solve(self.order)
        self.assertIsInstance(result, list)


# ---------------------------------------------------------------------------
# View integration tests
# ---------------------------------------------------------------------------

class NewOrderViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.topping = Topping.objects.create(name="Pepperoni")
        self.group = make_group("Alice's Group")
        self.restaurant = make_restaurant(toppings=[self.topping], group=self.group)
        from webapp.models import User
        self.user = User.objects.create_user(
            username='alice', email='alice@test.com', password='testpass',
        )
        self.alice = make_person("Alice")
        self.alice.user_account = self.user
        self.alice.save()
        self.bob = make_person("Bob")
        GroupMembership.objects.create(group=self.group, person=self.alice, is_admin=True)
        GroupMembership.objects.create(group=self.group, person=self.bob)
        self.client.force_login(self.user)

    def _new_order_url(self):
        return reverse('new_order', args=[self.group.pk])

    def test_select_group_single_group_redirects(self):
        response = self.client.get(reverse('order_select_group'))
        self.assertRedirects(response, self._new_order_url())

    def test_select_group_multi_group_shows_picker(self):
        group2 = make_group("Second Group")
        GroupMembership.objects.create(group=group2, person=self.alice)
        response = self.client.get(reverse('order_select_group'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a Group")

    def test_get_new_order_returns_200(self):
        response = self.client.get(self._new_order_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New Pizza Order")

    def test_post_invalid_form_shows_errors(self):
        response = self.client.post(self._new_order_url(), data={})
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'restaurant', 'This field is required.')

    def test_post_valid_form_creates_order_and_redirects(self):
        response = self.client.post(self._new_order_url(), data={
            'restaurant': self.restaurant.pk,
            'people': [self.bob.pk],
            'num_pizzas': 1,
            'optimization_mode': 'maximize_likes',
            'shareability_bonus_weight': '0',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/results/', response['Location'])
        self.assertEqual(Order.objects.count(), 1)

    def test_host_auto_added_to_people(self):
        # Alice is host (logged-in user) but not explicitly in people; she should be auto-included.
        response = self.client.post(self._new_order_url(), data={
            'restaurant': self.restaurant.pk,
            'people': [self.bob.pk],
            'num_pizzas': 1,
            'optimization_mode': 'maximize_likes',
            'shareability_bonus_weight': '0',
        })
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertIn(self.alice, order.people.all())

    def test_more_pizzas_than_people_shows_error(self):
        # alice (host) + bob = 2 people, so 5 pizzas should fail
        response = self.client.post(self._new_order_url(), data={
            'restaurant': self.restaurant.pk,
            'people': [self.bob.pk],
            'num_pizzas': 5,
            'optimization_mode': 'maximize_likes',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "more pizzas than people")

    def test_shareability_weight_stored_on_order(self):
        """POSTing shareability_bonus_weight=0.3 should store 0.3 on the created Order."""
        response = self.client.post(self._new_order_url(), data={
            'restaurant': self.restaurant.pk,
            'people': [self.bob.pk],
            'num_pizzas': 1,
            'optimization_mode': 'maximize_likes',
            'shareability_bonus_weight': '0.3',
        })
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertAlmostEqual(order.shareability_bonus_weight, 0.3)

    def test_invite_guests_creates_proto_order_and_redirects_to_draft(self):
        response = self.client.post(self._new_order_url(), data={
            'restaurant': self.restaurant.pk,
            'invite_guests': '1',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/draft/', response['Location'])
        proto = Order.objects.get()
        self.assertIsNotNone(proto.invite_token)
        self.assertFalse(proto.pizzas.exists())


class DraftOrderViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.topping = Topping.objects.create(name="Pepperoni")
        self.group = make_group("Alice's Group")
        self.restaurant = make_restaurant(toppings=[self.topping], group=self.group)
        from webapp.models import User
        self.user = User.objects.create_user(
            username='alice', email='alice@test.com', password='testpass',
        )
        self.alice = make_person("Alice")
        self.alice.user_account = self.user
        self.alice.save()
        self.bob = make_person("Bob")
        GroupMembership.objects.create(group=self.group, person=self.alice, is_admin=True)
        GroupMembership.objects.create(group=self.group, person=self.bob)
        self.client.force_login(self.user)
        import uuid
        self.proto_order = Order.objects.create(
            host=self.alice, group=self.group, restaurant=self.restaurant,
            num_pizzas=1, optimization_mode='maximize_likes', invite_token=uuid.uuid4(),
        )
        self.proto_order.people.add(self.alice)

    def _draft_url(self):
        return reverse('draft_order', args=[self.group.pk, self.proto_order.pk])

    def test_get_draft_order_returns_200(self):
        response = self.client.get(self._draft_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New Pizza Order")

    def test_post_draft_order_generates_and_redirects(self):
        response = self.client.post(self._draft_url(), data={
            'people': [self.bob.pk],
            'num_pizzas': 1,
            'optimization_mode': 'maximize_likes',
            'shareability_bonus_weight': '0',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/results/', response['Location'])

    def test_draft_order_solved_redirects_to_results(self):
        pizza = OrderedPizza.objects.create(order=self.proto_order)
        pizza.people.set([self.alice])
        response = self.client.get(self._draft_url())
        self.assertRedirects(response, reverse('order_results', args=[self.proto_order.pk]))


class OrderResultsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.topping = Topping.objects.create(name="Cheese")
        self.group = make_group()
        self.restaurant = make_restaurant(toppings=[self.topping], group=self.group)
        self.alice = make_person("Alice")
        self.order = make_order(self.restaurant, self.alice, [self.alice], group=self.group)
        # Orders without pizzas redirect; add one so the results page renders
        self.pizza = OrderedPizza.objects.create(order=self.order)
        self.pizza.people.set([self.alice])

    def test_results_page_returns_200(self):
        url = reverse('order_results', kwargs={'order_id': self.order.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pizza assignments")

    def test_results_page_shows_no_assignments_when_empty(self):
        # An order without pizzas redirects to the order form instead of showing results
        empty_order = make_order(self.restaurant, self.alice, [self.alice], group=self.group)
        url = reverse('order_results', kwargs={'order_id': empty_order.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_results_page_shows_pizza_when_assigned(self):
        self.pizza.toppings.set([self.topping])
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
        restaurant = make_restaurant(toppings=[t_pep, t_mush])
        alice = make_person("Alice", prefs={t_pep: PersonToppingPreference.ALLERGY})
        bob = make_person("Bob", prefs={t_pep: PersonToppingPreference.LIKE})
        order = make_order(restaurant, alice, [alice, bob], num_pizzas=1)

        pizzas = solve(order)

        for pizza in pizzas:
            left_top_ids = set(pizza.toppings.values_list('id', flat=True))
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

    # --- test_topping_cap ---

    def test_topping_cap(self):
        """No pizza half should have more than 3 toppings."""
        tops = self._make_toppings("A", "B", "C", "D", "E")
        restaurant = make_restaurant(name="Cap Restaurant", toppings=tops)
        alice = make_person("AliceCap", prefs={t: PersonToppingPreference.LIKE for t in tops})
        order = make_order(restaurant, alice, [alice], num_pizzas=1)

        pizzas = solve(order)

        for pizza in pizzas:
            self.assertLessEqual(pizza.toppings.count(), 3)

    # --- test_every_person_assigned ---

    def test_every_person_assigned(self):
        """All people in the order appear on exactly one pizza."""
        tops = self._make_toppings("Olive", "Bacon")
        restaurant = make_restaurant(name="Assign Restaurant", toppings=tops)
        alice = make_person("AliceA")
        bob = make_person("BobA")
        charlie = make_person("CharlieA")
        order = make_order(restaurant, alice, [alice, bob, charlie], num_pizzas=2)

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
        restaurant = make_restaurant(name="NonEmpty Restaurant", toppings=tops)
        alice = make_person("AliceNE")
        bob = make_person("BobNE")
        order = make_order(restaurant, alice, [alice, bob], num_pizzas=2)

        pizzas = solve(order)

        for pizza in pizzas:
            self.assertGreater(pizza.people.count(), 0, "Pizza has no people assigned")

    # --- test_maximize_likes_prefers_liked_toppings ---

    def test_maximize_likes_prefers_liked_toppings(self):
        """In maximize_likes mode, a liked topping should appear on the pizza."""
        t_like, t_neutral = self._make_toppings("LikedTopping", "NeutralTopping")
        restaurant = make_restaurant(name="Likes Restaurant", toppings=[t_like, t_neutral])
        alice = make_person("AliceLikes", prefs={t_like: PersonToppingPreference.LIKE})
        order = make_order(restaurant, alice, [alice], num_pizzas=1, optimization_mode='maximize_likes')

        pizzas = solve(order)

        self.assertEqual(len(pizzas), 1)
        topping_ids = set(pizzas[0].toppings.values_list('id', flat=True))
        self.assertIn(t_like.id, topping_ids, "Liked topping should be on the pizza")

    # --- test_minimize_dislikes_balances_scores ---

    def test_minimize_dislikes_balances_scores(self):
        """minimize_dislikes should maximize the worst-case pizza score vs maximize_likes."""
        # Two people each liking different toppings; 2 pizzas
        # maximize_likes might put all liked toppings on one pizza
        # minimize_dislikes should ensure a more balanced assignment
        t1, t2 = self._make_toppings("MinDisT1", "MinDisT2")
        restaurant = make_restaurant(name="MinDis Restaurant", toppings=[t1, t2])
        alice = make_person("AliceMD", prefs={t1: PersonToppingPreference.LIKE, t2: PersonToppingPreference.DISLIKE})
        bob = make_person("BobMD", prefs={t2: PersonToppingPreference.LIKE, t1: PersonToppingPreference.DISLIKE})
        people = [alice, bob]

        order_md = make_order(restaurant, alice, people, num_pizzas=2, optimization_mode='minimize_dislikes')
        pizzas_md = solve(order_md)

        # Each person should be on a separate pizza
        self.assertEqual(len(pizzas_md), 2)
        # Each pizza should have exactly 1 person
        for pizza in pizzas_md:
            self.assertEqual(pizza.people.count(), 1)
        # Each person gets their preferred topping, not the one they dislike
        for pizza in pizzas_md:
            person = pizza.people.first()
            topping_ids = set(pizza.toppings.values_list('id', flat=True))
            dislikes = set(PersonToppingPreference.objects.filter(
                person=person, preference=PersonToppingPreference.DISLIKE
            ).values_list('topping_id', flat=True))
            self.assertTrue(topping_ids.isdisjoint(dislikes),
                            f"{person.name} has a disliked topping on their pizza")

    # --- test_unrated_is_dislike_excludes_unrated_toppings ---

    def test_unrated_is_dislike_excludes_unrated_toppings(self):
        """When unrated_is_dislike=True, unrated toppings should not appear on pizza."""
        t_unrated, t_liked = self._make_toppings("UnratedTop", "LikedTop2")
        restaurant = make_restaurant(name="Unrated Restaurant", toppings=[t_unrated, t_liked])
        # Person has unrated_is_dislike=True and only likes t_liked
        alice = make_person("AliceUnrated", unrated_is_dislike=True,
                            prefs={t_liked: PersonToppingPreference.LIKE})
        order = make_order(restaurant, alice, [alice], num_pizzas=1, optimization_mode='maximize_likes')

        pizzas = solve(order)

        self.assertEqual(len(pizzas), 1)
        left_ids = set(pizzas[0].toppings.values_list('id', flat=True))
        self.assertNotIn(t_unrated.id, left_ids,
                         "Unrated topping should be excluded when unrated_is_dislike=True")

    # --- test_unrated_is_neutral_includes_unrated_toppings ---

    def test_unrated_is_neutral_includes_unrated_toppings(self):
        """When unrated_is_dislike=False, unrated toppings may appear on pizza."""
        # To force the solver to pick the unrated topping, make it the only available one
        t_unrated, = self._make_toppings("NeutralUnrated")
        restaurant = make_restaurant(name="Neutral Restaurant", toppings=[t_unrated])
        # Person has no preferences recorded (default neutral) and unrated_is_dislike=False
        alice = make_person("AliceNeutral", unrated_is_dislike=False)
        # Give alice a LIKE for the unrated topping so solver picks it
        PersonToppingPreference.objects.create(
            person=alice, topping=t_unrated, preference=PersonToppingPreference.LIKE
        )
        order = make_order(restaurant, alice, [alice], num_pizzas=1, optimization_mode='maximize_likes')

        pizzas = solve(order)

        self.assertEqual(len(pizzas), 1)
        left_ids = set(pizzas[0].toppings.values_list('id', flat=True))
        self.assertIn(t_unrated.id, left_ids,
                      "Liked topping should appear on pizza")

    # --- test_shareability_k1_no_division_by_zero ---

    def test_shareability_k1_no_division_by_zero(self):
        """With K=1, a non-zero shareability weight should not cause a division-by-zero error."""
        t1, = self._make_toppings("K1ShareTop")
        restaurant = make_restaurant(name="K1Share Restaurant", toppings=[t1])
        alice = make_person("AliceK1Share", prefs={t1: PersonToppingPreference.LIKE})
        bob = make_person("BobK1Share")
        order = make_order(restaurant, alice, [alice, bob], num_pizzas=1,
                           shareability_bonus_weight=0.8)

        pizzas = solve(order)

        self.assertEqual(len(pizzas), 1)
        people_ids = set(pizzas[0].people.values_list('id', flat=True))
        self.assertIn(alice.id, people_ids)
        self.assertIn(bob.id, people_ids)

    # --- test_shareability_spreads_liked_topping_to_non_assigned_pizza ---

    def test_shareability_spreads_liked_topping_to_non_assigned_pizza(self):
        """With shareability, a topping liked by Alice but neutral for Bob appears on Bob's pizza.

        Without shareability (w=0): the solver has no objective incentive to add a 0-score
        topping to Bob's pizza, so it stays off.

        With shareability (f=0.8, K=2 → w=0.8): Alice's non-assigned contribution (+0.8)
        to Bob's pizza score makes adding the topping worthwhile.
        """
        t1, = self._make_toppings("SpreadTop")
        restaurant = make_restaurant(name="Spread Restaurant", toppings=[t1])
        alice = make_person("AliceSpread", prefs={t1: PersonToppingPreference.LIKE})
        bob = make_person("BobSpread")  # Bob has no rated preference for t1

        # WITHOUT shareability: T1 has 0 objective contribution on Bob's pizza, so solver omits it.
        order_no = make_order(restaurant, alice, [alice, bob], num_pizzas=2,
                              optimization_mode='maximize_likes', shareability_bonus_weight=0)
        pizzas_no = solve(order_no)
        bob_pizza_no = next(p for p in pizzas_no if bob in p.people.all())
        self.assertNotIn(t1.id, set(bob_pizza_no.toppings.values_list('id', flat=True)),
                         "Without shareability, T1 should not appear on Bob's neutral pizza")

        # WITH shareability: Alice's non-assigned like (+0.8) gives positive incentive for T1 on
        # Bob's pizza.
        order_yes = make_order(restaurant, alice, [alice, bob], num_pizzas=2,
                               optimization_mode='maximize_likes', shareability_bonus_weight=0.8)
        pizzas_yes = solve(order_yes)
        bob_pizza_yes = next(p for p in pizzas_yes if bob in p.people.all())
        self.assertIn(t1.id, set(bob_pizza_yes.toppings.values_list('id', flat=True)),
                      "With shareability, Alice's non-assigned like should put T1 on Bob's pizza")
