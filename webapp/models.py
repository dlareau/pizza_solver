import uuid

from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """User model for authentication - represents accounts in the system."""
    # AbstractUser already provides: username, first_name, last_name, email,
    # password, is_staff, is_active, is_superuser, date_joined, last_login

    # Override email to make it required and unique
    email = models.EmailField(unique=True, blank=False)

    def __str__(self):
        # Use email if name fields aren't set, otherwise construct from name
        if self.first_name or self.last_name:
            return f"{self.first_name} {self.last_name}".strip() or self.email
        return self.email


class Person(models.Model):
    """Represents a participant — either a persistent user (user_account set) or a guest (user_account null)."""
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    comments = models.TextField(blank=True, null=True)

    user_account = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='person_profile',
        help_text="Linked user account (null for guests)"
    )
    guest_for_order = models.ForeignKey(
        'Order',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='guest_persons',
        help_text="Set for guest Persons; null for persistent users"
    )

    unrated_is_dislike = models.BooleanField(
        default=False,
        help_text="If True, toppings with no recorded preference are treated as Dislike (-1) during optimization."
    )
    preferred_toppings = models.ManyToManyField('Topping', through='PersonToppingPreference', related_name='people_with_preference')

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "People"


class PizzaGroup(models.Model):
    """A group of people who order pizza together."""
    name = models.CharField(max_length=200)
    invite_token = models.UUIDField(default=uuid.uuid4, unique=True)
    members = models.ManyToManyField('Person', through='GroupMembership', related_name='pizza_groups')

    def __str__(self):
        return self.name


class GroupMembership(models.Model):
    """Through model for PizzaGroup <-> Person with admin flag."""
    group = models.ForeignKey(PizzaGroup, on_delete=models.CASCADE, related_name='memberships')
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='group_memberships')
    is_admin = models.BooleanField(default=False)

    class Meta:
        unique_together = [['group', 'person']]

    def __str__(self):
        role = "admin" if self.is_admin else "member"
        return f"{self.person.name} in {self.group.name} ({role})"


class Topping(models.Model):
    """Represents a pizza topping."""
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class PizzaRestaurant(models.Model):
    """Represents a pizza restaurant."""
    name = models.CharField(max_length=200)
    group = models.ForeignKey(
        'PizzaGroup',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='restaurants',
        help_text="Owning group (null = public restaurant, visible to everyone)"
    )
    metadata = models.JSONField(default=dict, blank=True, null=True)
    toppings = models.ManyToManyField('Topping', through='RestaurantTopping', related_name='restaurants_offering')

    def __str__(self):
        return self.name


class PersonToppingPreference(models.Model):
    """Through model for person-topping preferences with named preference levels."""
    ALLERGY = -2
    DISLIKE = -1
    NEUTRAL = 0
    LIKE = 1

    PREFERENCE_CHOICES = [
        (ALLERGY, 'Allergy'),
        (DISLIKE, 'Dislike'),
        (NEUTRAL, 'Neutral'),
        (LIKE, 'Like'),
    ]

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='topping_preferences')
    topping = models.ForeignKey(Topping, on_delete=models.CASCADE, related_name='person_preferences')
    preference = models.IntegerField(
        choices=PREFERENCE_CHOICES,
        default=NEUTRAL,
        help_text="Preference level: ALLERGY (-2) is a hard constraint, DISLIKE (-1) is minimized, NEUTRAL (0), LIKE (1) is maximized"
    )

    class Meta:
        unique_together = [['person', 'topping']]
        verbose_name_plural = "Person Topping Preferences"

    def __str__(self):
        return f"{self.person.name} - {self.topping.name} ({self.get_preference_display()})"


class RestaurantTopping(models.Model):
    """Through model indicating which restaurants have which toppings available."""
    restaurant = models.ForeignKey(PizzaRestaurant, on_delete=models.CASCADE, related_name='available_toppings')
    topping = models.ForeignKey(Topping, on_delete=models.CASCADE, related_name='restaurants')

    class Meta:
        unique_together = [['restaurant', 'topping']]
        verbose_name_plural = "Restaurant Toppings"

    def __str__(self):
        return f"{self.restaurant.name} - {self.topping.name}"


class Order(models.Model):
    """Represents a pizza order."""
    OPTIMIZATION_MODE_CHOICES = [
        ('maximize_likes', 'Maximize Likes'),
        ('minimize_dislikes', 'Minimize Dislikes'),
    ]

    host = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='hosted_orders')
    restaurant = models.ForeignKey(PizzaRestaurant, on_delete=models.CASCADE, related_name='orders')
    people = models.ManyToManyField(Person, related_name='orders')
    group = models.ForeignKey(
        'PizzaGroup',
        on_delete=models.PROTECT,
        related_name='orders',
    )
    num_pizzas = models.IntegerField(default=1, help_text="Number of pizzas to order")
    optimization_mode = models.CharField(
        max_length=20, choices=OPTIMIZATION_MODE_CHOICES, default='minimize_dislikes',
        help_text="Which optimization strategy to use"
    )
    invite_token = models.UUIDField(null=True, blank=True, unique=True)
    metadata = models.JSONField(default=dict, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order #{self.id} - {self.restaurant.name} ({self.created_at.date()})"


class OrderedPizza(models.Model):
    """Represents an individual pizza within an order."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='pizzas')
    toppings = models.ManyToManyField(Topping, related_name='pizzas', blank=True)
    people = models.ManyToManyField(Person, related_name='ordered_pizzas')

    def __str__(self):
        return f"Pizza #{self.id} - Order #{self.order.id}"
