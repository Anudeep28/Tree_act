from django.urls import path
from . import views
from .auth_views import register_view
from .payment_views import subscribe_view, payment_success_view

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', register_view, name='register'),
    path('process/<int:search_id>/', views.process_street, name='process_street'),
    path('results/<int:search_id>/', views.results, name='results'),
    path('status/<int:search_id>/', views.search_status, name='search_status'),
    path('subscribe/', subscribe_view, name='subscribe'),
    path('payment_success/', payment_success_view, name='payment_success'),
]
