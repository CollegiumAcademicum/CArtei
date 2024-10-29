from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic.base import RedirectView

from . import views

urlpatterns = [
    path("", views.dashboard, name="home"),  # Stelle sicher, dass dieser Name existiert
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="/"), name="logout"),
    path("profile/", views.profile, name="profile"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("save_order/", views.save_tile_order, name="save_tile_order"),
    path("accounts/login/", RedirectView.as_view(url="/login/")),  # Redirect to the correct path
    path("search_suggestions/", views.search_suggestions, name="search_suggestions"),  # Neue URL für Suchvorschläge
    path("entries/", views.entry_list, name="entry_list"),
    path("entries/new/", views.entry_create, name="entry_create"),
    path("entries/edit/<int:pk>/", views.entry_update, name="entry_update"),
    path("entries/delete/<int:pk>/", views.entry_delete, name="entry_delete"),
    path("entries/populate/", views.populate_from_csv, name="populate_from_csv"),
]
