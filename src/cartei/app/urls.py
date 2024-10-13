from django.urls import path
from . import views

urlpatterns = [
    path("", views.entry_list, name="entry_list"),
    path("new/", views.entry_create, name="entry_create"),
    path("edit/<int:pk>/", views.entry_update, name="entry_update"),
    path("delete/<int:pk>/", views.entry_delete, name="entry_delete"),
    path("populate/", views.populate_from_csv, name="populate_from_csv"),
]
