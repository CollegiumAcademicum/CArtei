from django.urls import path

from app.views import abfragen, admin_views, dashboard, tenant

urlpatterns = [
    path("dashboard/", dashboard.dashboard, name="dashboard"),
    path("abfragen/", abfragen.abfragen_list, name="abfragen_list"),
    path("abfragen/new/", abfragen.abfrage_new, name="abfrage_new"),
    path("abfragen/<int:pk>/", abfragen.abfrage_detail, name="abfrage_detail"),
    path("abfragen/<int:pk>/ag/<str:ag_name>/", abfragen.ag_edit, name="ag_edit"),
    path("abfragen/<int:pk>/tenants/", abfragen.abfrage_tenants, name="abfrage_tenants"),
    path("abfragen/<int:pk>/delete/", abfragen.abfrage_delete, name="abfrage_delete"),
    path("cluster/", abfragen.belegium, name="belegium"),
    path("tenants/<int:pk>/", tenant.tenant_detail, name="tenant_detail"),
    path("admin/", admin_views.admin_portal, name="admin_portal"),
    path("admin/sync-from-ldap/", admin_views.sync_from_ldap, name="sync_from_ldap"),
    path("admin/permissions/", admin_views.permission_matrix, name="permission_matrix"),
]
