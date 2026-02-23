from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import (
    GroupMembership, Order, OrderedPizza,
    Person, PersonToppingPreference, PizzaGroup, PizzaRestaurant, Topping, User, RestaurantTopping,
)


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
    list_display = ('name', 'email', 'user_account', 'guest_for_order', 'unrated_is_dislike')
    search_fields = ('name', 'email')
    fields = ('name', 'email', 'comments', 'user_account', 'guest_for_order', 'unrated_is_dislike')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user_account', 'guest_for_order')


@admin.register(PizzaGroup)
class PizzaGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'member_count')
    search_fields = ('name',)

    def member_count(self, obj):
        return obj.members.count()
    member_count.short_description = 'Members'


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ('group', 'person', 'is_admin')
    list_filter = ('group', 'is_admin')
    search_fields = ('group__name', 'person__name', 'person__email')


@admin.register(Topping)
class ToppingAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(PizzaRestaurant)
class PizzaRestaurantAdmin(admin.ModelAdmin):
    list_display = ('name', 'group')
    search_fields = ('name',)
    list_filter = ('group',)


@admin.register(PersonToppingPreference)
class PersonToppingPreferenceAdmin(admin.ModelAdmin):
    list_display = ('person', 'topping', 'preference')
    list_filter = ('topping', 'preference')
    search_fields = ('person__name', 'person__email', 'topping__name')


@admin.register(RestaurantTopping)
class RestaurantToppingAdmin(admin.ModelAdmin):
    list_display = ('restaurant', 'topping')
    list_filter = ('restaurant', 'topping')
    search_fields = ('restaurant__name', 'topping__name')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'host', 'restaurant', 'group', 'num_pizzas', 'optimization_mode', 'invite_token', 'created_at')
    list_filter = ('restaurant', 'optimization_mode', 'created_at')
    search_fields = ('host__name', 'host__email', 'restaurant__name')
    readonly_fields = ('invite_token',)
    filter_horizontal = ('people',)
    date_hierarchy = 'created_at'


@admin.register(OrderedPizza)
class OrderedPizzaAdmin(admin.ModelAdmin):
    list_display = ('id', 'order')
    list_filter = ('order__restaurant',)
    filter_horizontal = ('toppings', 'people')
