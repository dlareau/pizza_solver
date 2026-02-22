from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, Person, Topping, PizzaVendor, PersonToppingPreference, VendorTopping, Order, OrderedPizza


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for User (authentication model)."""
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name')}),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'password1', 'password2'),
        }),
    )
    list_display = ('email', 'first_name', 'last_name', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('is_staff', 'is_superuser', 'is_active')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)
    filter_horizontal = ('groups', 'user_permissions')


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    """Admin configuration for Person (can exist with or without user account)."""
    list_display = ('name', 'email', 'user_account', 'unrated_is_dislike')
    search_fields = ('name', 'email')
    fields = ('name', 'email', 'comments', 'user_account', 'unrated_is_dislike')
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user_account')


@admin.register(Topping)
class ToppingAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(PizzaVendor)
class PizzaVendorAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    # Note: toppings uses a through model (VendorTopping),
    # so it cannot be in filter_horizontal - manage it via VendorToppingAdmin


@admin.register(PersonToppingPreference)
class PersonToppingPreferenceAdmin(admin.ModelAdmin):
    list_display = ('person', 'topping', 'preference')
    list_filter = ('topping', 'preference')
    search_fields = ('person__name', 'person__email', 'topping__name')


@admin.register(VendorTopping)
class VendorToppingAdmin(admin.ModelAdmin):
    list_display = ('vendor', 'topping')
    list_filter = ('vendor', 'topping')
    search_fields = ('vendor__name', 'topping__name')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'host', 'vendor', 'num_pizzas', 'optimization_mode', 'created_at')
    list_filter = ('vendor', 'optimization_mode', 'created_at')
    search_fields = ('host__name', 'host__email', 'vendor__name')
    filter_horizontal = ('people',)
    date_hierarchy = 'created_at'


@admin.register(OrderedPizza)
class OrderedPizzaAdmin(admin.ModelAdmin):
    list_display = ('id', 'order')
    list_filter = ('order__vendor',)
    filter_horizontal = ('toppings', 'people')
