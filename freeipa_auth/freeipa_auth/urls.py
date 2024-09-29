from django.urls import path
from django.views.generic.base import RedirectView
from django.contrib.auth import views as auth_views
from .views import profile, dashboard, save_tile_order

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),
    path('profile/', profile, name='profile'),
    path('dashboard/', dashboard, name='dashboard'),
    path('', dashboard, name='home'),  # Stelle sicher, dass dieser Name existiert
    path('save_order/', save_tile_order, name='save_tile_order'),
    path('accounts/login/', RedirectView.as_view(url='/login/')),  # Redirect to the correct path
]
