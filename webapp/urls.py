from django.urls import path
from . import views

urlpatterns = [
    path('', views.create_order, name='index'),
    path('orders/new/', views.create_order, name='create_order'),
    path('orders/<int:order_id>/results/', views.order_results, name='order_results'),
    path('orders/<int:order_id>/cancel-invite/', views.order_cancel_invite, name='order_cancel_invite'),
    path('orders/<int:order_id>/people-partial/', views.order_people_partial, name='order_people_partial'),
    path('orders/join/<uuid:invite_token>/', views.order_join, name='order_join'),

    path('toppings/', views.topping_list, name='topping_list'),
    path('toppings/new/', views.topping_create, name='topping_create'),
    path('toppings/<int:pk>/edit/', views.topping_edit, name='topping_edit'),
    path('toppings/<int:pk>/merge/', views.topping_merge, name='topping_merge'),
    path('toppings/<int:pk>/delete/', views.topping_delete, name='topping_delete'),

    path('restaurants/', views.restaurant_list, name='restaurant_list'),
    path('restaurants/new/', views.restaurant_create, name='restaurant_create'),
    path('restaurants/<int:pk>/edit/', views.restaurant_edit, name='restaurant_edit'),
    path('restaurants/<int:pk>/delete/', views.restaurant_delete, name='restaurant_delete'),

    path('profile/edit/', views.profile_edit, name='profile_edit'),

    path('groups/', views.group_list, name='group_list'),
    path('groups/new/', views.group_create, name='group_create'),
    path('groups/<int:pk>/', views.group_detail, name='group_detail'),
    path('groups/<int:pk>/delete/', views.group_delete, name='group_delete'),
    path('groups/join/<uuid:token>/', views.group_join, name='group_join'),
    path('groups/<int:pk>/reset-invite/', views.group_reset_invite, name='group_reset_invite'),
    path('groups/<int:pk>/remove-member/<int:person_pk>/', views.group_remove_member, name='group_remove_member'),

]
