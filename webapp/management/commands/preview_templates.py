"""
Management command to preview all webapp templates in the browser.

Usage:
    python manage.py preview_templates

Creates minimal test data inside a transaction that is rolled back on clean
exit, renders all major templates via Django's test client, writes the HTML
to a temp directory, and opens one browser tab per page.

Running this command never modifies the database.
"""

import time
import uuid
import webbrowser
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.test import Client

from webapp.models import (
    GroupMembership, Order, OrderedPizza,
    Person, PizzaGroup, PizzaRestaurant, Topping, User, RestaurantTopping,
)

PREVIEW_EMAIL = "preview@pizza.test"
ALICE_EMAIL   = "alice@pizza.test"
GROUP_NAME    = "Preview Group"
GROUP2_NAME   = "Preview Group 2"
RESTAURANT_NAME = "Preview Pizza"
PREVIEW_TOPPINGS = [
    "Preview Cheese",
    "Preview Pepperoni",
    "Preview Mushrooms",
    "Preview Sausage",
    "Preview Onions",
    "Preview Peppers",
    "Preview Olives",
    "Preview Spinach",
    "Preview Chicken",
    "Preview Pineapple",
]

PAGE_LABELS = [
    'order_create_step2',
    'order_create_proto',
    'order_create_multi_group',
    'order_results',
    'profile_edit',
    'profile_setup',
    'guest_join_new',
    'guest_join_solved',
    'group_list',
    'group_detail',
    'group_form_create',
    'group_confirm_delete',
    'restaurant_list',
    'restaurant_form_create',
    'restaurant_form_multi_group',
    'restaurant_confirm_delete',
    'topping_list',
    'topping_form_create',
    'topping_merge',
    'topping_confirm_delete',
    'import',
    'sign_in',
    'sign_up',
]


class Command(BaseCommand):
    help = "Render all webapp templates to a temp dir and open them in the browser (no DB changes)."

    def add_arguments(self, parser):
        parser.add_argument(
            'template',
            nargs='?',
            choices=PAGE_LABELS,
            help="Template label to preview (omit to select interactively).",
        )

    def handle(self, *args, **options):
        if options['template']:
            selected_label = options['template']
        else:
            selected_label = self._prompt_selection()
        self.stdout.write("Setting up preview data...")
        with transaction.atomic():
            ctx = self._setup_data()
            pages = self._build_pages(ctx)
            if selected_label is not None:
                pages = [(l, u, a) for l, u, a in pages if l == selected_label]
            saved = self._fetch_pages(pages, ctx['user'])
            transaction.set_rollback(True)  # rolls back on clean exit — no DB changes persist
        self._open_pages(saved)
        self.stdout.write(self.style.SUCCESS("Done."))

    def _prompt_selection(self):
        """Print a numbered menu and return the chosen label, or None for all."""
        self.stdout.write("\nSelect a template to preview:")
        self.stdout.write("  0) all")
        for i, label in enumerate(PAGE_LABELS, 1):
            self.stdout.write(f"  {i}) {label}")
        while True:
            raw = input("Choice: ").strip()
            try:
                choice = int(raw)
                if choice == 0:
                    return None
                if 1 <= choice <= len(PAGE_LABELS):
                    return PAGE_LABELS[choice - 1]
            except ValueError:
                pass
            self.stdout.write(f"Please enter a number between 0 and {len(PAGE_LABELS)}.")

    # ------------------------------------------------------------------
    # Data setup
    # ------------------------------------------------------------------

    def _setup_data(self) -> dict:
        # 1. Preview user — is_staff so topping/import pages are accessible
        user, _ = User.objects.get_or_create(
            email=PREVIEW_EMAIL,
            defaults={'username': PREVIEW_EMAIL, 'is_staff': True},
        )
        if not user.is_staff:
            user.is_staff = True
            user.save()

        # 2. Preview person linked to preview user
        person, _ = Person.objects.get_or_create(
            user_account=user,
            defaults={'name': 'Preview User', 'email': PREVIEW_EMAIL},
        )

        # 3. Alice — second member makes group/order pages more realistic
        alice_user, _ = User.objects.get_or_create(
            email=ALICE_EMAIL,
            defaults={'username': ALICE_EMAIL, 'is_staff': False},
        )
        alice, _ = Person.objects.get_or_create(
            user_account=alice_user,
            defaults={'name': 'Alice', 'email': ALICE_EMAIL},
        )

        # 4. Group with preview user as admin + alice as member
        group, _ = PizzaGroup.objects.get_or_create(name=GROUP_NAME)
        admin_gm, _ = GroupMembership.objects.get_or_create(
            group=group, person=person,
            defaults={'is_admin': True},
        )
        if not admin_gm.is_admin:
            admin_gm.is_admin = True
            admin_gm.save()
        GroupMembership.objects.get_or_create(group=group, person=alice)

        # 4b. Second group — makes multi-group views renderable
        group2, _ = PizzaGroup.objects.get_or_create(name=GROUP2_NAME)
        GroupMembership.objects.get_or_create(group=group2, person=person)

        # 5. Ten preview toppings
        toppings = []
        for name in PREVIEW_TOPPINGS:
            t, _ = Topping.objects.get_or_create(name=name)
            toppings.append(t)

        # 6. Restaurant in preview group with all preview toppings
        restaurant, _ = PizzaRestaurant.objects.get_or_create(
            name=RESTAURANT_NAME,
            defaults={'group': group},
        )
        if restaurant.group_id != group.pk:
            restaurant.group = group
            restaurant.save()
        for t in toppings:
            RestaurantTopping.objects.get_or_create(restaurant=restaurant, topping=t)

        # 7. Proto-order: invite_token set, no OrderedPizza children
        #    (renders guest-invite mode of order_create.html and first-time guests/join.html)
        proto_order = (
            Order.objects
            .filter(host=person, restaurant=restaurant, group=group, invite_token__isnull=False)
            .exclude(pk__in=OrderedPizza.objects.values('order_id'))
            .first()
        )
        if proto_order is None:
            proto_order = Order.objects.create(
                host=person,
                restaurant=restaurant,
                group=group,
                num_pizzas=2,
                invite_token=uuid.uuid4(),
            )
            proto_order.people.add(person)

        # 8. Solved order: no invite_token, has OrderedPizza children
        #    (renders order_results.html)
        solved_order = (
            Order.objects
            .filter(host=person, restaurant=restaurant, group=group, invite_token__isnull=True)
            .filter(pk__in=OrderedPizza.objects.values('order_id'))
            .first()
        )
        if solved_order is None:
            solved_order = Order.objects.create(
                host=person,
                restaurant=restaurant,
                group=group,
                num_pizzas=3,
                invite_token=None,
            )
            solved_order.people.set([person, alice])
        else:
            solved_order.num_pizzas = 3
            solved_order.save()
            solved_order.pizzas.all().delete()
        pizza1 = OrderedPizza.objects.create(order=solved_order)
        pizza1.toppings.set(toppings[:3])
        pizza1.people.add(person)
        pizza2 = OrderedPizza.objects.create(order=solved_order)
        pizza2.toppings.set(toppings[3:6])
        pizza2.people.add(alice)
        pizza3 = OrderedPizza.objects.create(order=solved_order)
        pizza3.toppings.set(toppings[6:9])
        pizza3.people.add(person, alice)

        # 9. Solved guest order: invite_token set AND has OrderedPizza children
        #    (renders guests/join.html in "already solved" state)
        solved_guest_order = (
            Order.objects
            .filter(host=person, restaurant=restaurant, group=group, invite_token__isnull=False)
            .filter(pk__in=OrderedPizza.objects.values('order_id'))
            .first()
        )
        if solved_guest_order is None:
            solved_guest_order = Order.objects.create(
                host=person,
                restaurant=restaurant,
                group=group,
                num_pizzas=1,
                invite_token=uuid.uuid4(),
            )
            solved_guest_order.people.add(person)
            pizza = OrderedPizza.objects.create(order=solved_guest_order)
            pizza.toppings.set(toppings[:3])
            pizza.people.add(person)

        self.stdout.write(
            f"  group={group.pk}  group2={group2.pk}  restaurant={restaurant.pk}  "
            f"proto={proto_order.pk}  solved={solved_order.pk}  "
            f"solved-guest={solved_guest_order.pk}"
        )

        return {
            'user': user,
            'person': person,
            'alice': alice,
            'group': group,
            'group2': group2,
            'toppings': toppings,
            'restaurant': restaurant,
            'proto_order': proto_order,
            'solved_order': solved_order,
            'solved_guest_order': solved_guest_order,
        }

    # ------------------------------------------------------------------
    # Page list
    # ------------------------------------------------------------------

    def _build_pages(self, ctx) -> list:
        g   = ctx['group']
        r   = ctx['restaurant']
        t   = ctx['toppings'][0]
        po  = ctx['proto_order']
        so  = ctx['solved_order']
        sgo = ctx['solved_guest_order']

        # Tuples are (label, url, authenticated).
        # authenticated=False uses an anonymous client — needed for pages that
        # redirect away when the user is already logged in.
        return [
            ('order_create_step2',    f'/orders/new/?group={g.pk}',          True),
            ('order_create_proto',    f'/orders/new/?order={po.pk}&group={g.pk}', True),
            ('order_create_multi_group', '/orders/new/',                      True),
            ('order_results',         f'/orders/{so.pk}/results/',            True),
            ('profile_edit',          '/profile/edit/',                       True),
            ('profile_setup',         '/profile/edit/?setup=1',               True),
            ('guest_join_new',        f'/orders/join/{po.invite_token}/',     True),
            ('guest_join_solved',     f'/orders/join/{sgo.invite_token}/',    True),
            ('group_list',            '/groups/',                             True),
            ('group_detail',          f'/groups/{g.pk}/',                     True),
            ('group_form_create',     '/groups/new/',                         True),
            ('group_confirm_delete',  f'/groups/{g.pk}/delete/',              True),
            ('restaurant_list',       '/restaurants/',                        True),
            ('restaurant_form_create', f'/restaurants/new/?group={g.pk}',    True),
            ('restaurant_form_multi_group', '/restaurants/new/',              True),
            ('restaurant_confirm_delete', f'/restaurants/{r.pk}/delete/',    True),
            ('topping_list',          '/toppings/',                           True),
            ('topping_form_create',   '/toppings/new/',                       True),
            ('topping_merge',         f'/toppings/{t.pk}/merge/',             True),
            ('topping_confirm_delete', f'/toppings/{t.pk}/delete/',           True),
            ('import',                '/import/',                             True),
            ('sign_in',               '/accounts/login/',                     False),
            ('sign_up',               '/accounts/signup/',                    False),
        ]

    # ------------------------------------------------------------------
    # Page fetching
    # ------------------------------------------------------------------

    def _fetch_pages(self, pages, user) -> list:
        tmpdir = Path.home() / 'pizza_previews' / uuid.uuid4().hex[:8]
        tmpdir.mkdir(parents=True, exist_ok=True)
        self.stdout.write(f"  HTML output: {tmpdir}")

        auth_client = Client()
        auth_client.force_login(user)
        anon_client = Client()

        saved = []
        for label, url, authenticated in pages:
            client = auth_client if authenticated else anon_client
            response = client.get(url)
            if response.status_code == 200:
                path = tmpdir / f'{label}.html'
                path.write_bytes(response.content)
                saved.append((label, path))
                self.stdout.write(f'  [OK  ] {label}')
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'  [SKIP] {label} -> {url}  (HTTP {response.status_code})'
                    )
                )

        return saved

    # ------------------------------------------------------------------
    # Browser opening
    # ------------------------------------------------------------------

    def _open_pages(self, saved) -> None:
        self.stdout.write(f"Opening {len(saved)} browser tab(s)...")
        for _label, path in saved:
            webbrowser.open_new_tab(f'file://{path}')
            time.sleep(0.3)
