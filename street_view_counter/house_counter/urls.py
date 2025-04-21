from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('process/<int:search_id>/', views.process_street, name='process_street'),
    path('results/<int:search_id>/', views.results, name='results'),
    path('status/<int:search_id>/', views.search_status, name='search_status'),
]
