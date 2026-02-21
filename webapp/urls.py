from django.urls import path
from . import views

urlpatterns = [
    path('orders/new/', views.create_order, name='create_order'),
    path('orders/<int:order_id>/results/', views.order_results, name='order_results'),
]
