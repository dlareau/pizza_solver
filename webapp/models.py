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
    """Represents a person who can order pizza (with or without an account)."""
    name = models.CharField(max_length=200)
    email = models.EmailField()
    comments = models.TextField(blank=True, null=True)
    
    # Optional link to User account (if they have one)
    user_account = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='person_profile',
        help_text="Optional link to user account if this person has registered"
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


class Topping(models.Model):
    """Represents a pizza topping."""
    name = models.CharField(max_length=100, unique=True)
    
    def __str__(self):
        return self.name


class PizzaVendor(models.Model):
    """Represents a pizza vendor/restaurant."""
    name = models.CharField(max_length=200)
    metadata = models.JSONField(default=dict, blank=True, null=True)
    toppings = models.ManyToManyField('Topping', through='VendorTopping', related_name='vendors_offering')
    
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


class VendorTopping(models.Model):
    """Through model indicating which vendors have which toppings available."""
    vendor = models.ForeignKey(PizzaVendor, on_delete=models.CASCADE, related_name='available_toppings')
    topping = models.ForeignKey(Topping, on_delete=models.CASCADE, related_name='vendors')
    
    class Meta:
        unique_together = [['vendor', 'topping']]
        verbose_name_plural = "Vendor Toppings"
    
    def __str__(self):
        return f"{self.vendor.name} - {self.topping.name}"


class Order(models.Model):
    """Represents a pizza order."""
    PIZZA_MODE_CHOICES = [
        ('whole', 'Whole pizzas only'),
        ('half', 'Half-and-half allowed'),
    ]
    OPTIMIZATION_MODE_CHOICES = [
        ('maximize_likes', 'Maximize Likes'),
        ('minimize_dislikes', 'Minimize Dislikes'),
    ]

    host = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='hosted_orders')
    vendor = models.ForeignKey(PizzaVendor, on_delete=models.CASCADE, related_name='orders')
    people = models.ManyToManyField(Person, related_name='orders')
    num_pizzas = models.IntegerField(default=1, help_text="Number of pizzas to order")
    pizza_mode = models.CharField(
        max_length=5, choices=PIZZA_MODE_CHOICES, default='whole',
        help_text="Whether half-and-half pizzas are allowed"
    )
    optimization_mode = models.CharField(
        max_length=20, choices=OPTIMIZATION_MODE_CHOICES, default='maximize_likes',
        help_text="Which optimization strategy to use"
    )
    metadata = models.JSONField(default=dict, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order #{self.id} - {self.vendor.name} ({self.created_at.date()})"


class OrderedPizza(models.Model):
    """Represents an individual pizza within an order.

    For whole-mode orders, only left_toppings is used.
    For half-mode orders, left_toppings = left half, right_toppings = right half.
    """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='pizzas')
    left_toppings = models.ManyToManyField(Topping, related_name='pizzas_as_left_topping', blank=True)
    right_toppings = models.ManyToManyField(Topping, related_name='pizzas_as_right_topping', blank=True)
    people = models.ManyToManyField(Person, related_name='ordered_pizzas')

    def __str__(self):
        return f"Pizza #{self.id} - Order #{self.order.id}"
