from django.urls import path

from app.views import admin_views

urlpatterns = [
    path("admin/sync-from-ldap/", admin_views.sync_from_ldap, name="sync_from_ldap"),
]
