from django.urls import path
from . import views

urlpatterns = [
    path('', views.create_order, name='index'),
    path('orders/new/', views.create_order, name='create_order'),
    path('orders/<int:order_id>/results/', views.order_results, name='order_results'),

    path('toppings/', views.topping_list, name='topping_list'),
    path('toppings/new/', views.topping_create, name='topping_create'),
    path('toppings/<int:pk>/edit/', views.topping_edit, name='topping_edit'),
    path('toppings/<int:pk>/merge/', views.topping_merge, name='topping_merge'),
    path('toppings/<int:pk>/delete/', views.topping_delete, name='topping_delete'),

    path('vendors/', views.vendor_list, name='vendor_list'),
    path('vendors/new/', views.vendor_create, name='vendor_create'),
    path('vendors/<int:pk>/edit/', views.vendor_edit, name='vendor_edit'),
    path('vendors/<int:pk>/delete/', views.vendor_delete, name='vendor_delete'),

    path('import/', views.import_data, name='import_data'),

    path('profile/setup/', views.guest_setup, name='guest_setup'),
    path('profile/magic/<uuid:token>/', views.magic_link, name='magic_link'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
]
