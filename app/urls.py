from django.urls import path

from app.views import abfragen, admin_views, dashboard, enrollment_proof, notes, tenant

urlpatterns = [
    path("dashboard/", dashboard.dashboard, name="dashboard"),
    path("abfragen/", abfragen.abfragen_list, name="abfragen_list"),
    path("abfragen/new/", abfragen.abfrage_new, name="abfrage_new"),
    path("abfragen/<int:pk>/", abfragen.abfrage_detail, name="abfrage_detail"),
    path("abfragen/<int:pk>/ag/<str:ag_name>/", abfragen.ag_edit, name="ag_edit"),
    path("abfragen/<int:pk>/tenants/", abfragen.abfrage_tenants, name="abfrage_tenants"),
    path("abfragen/<int:pk>/delete/", abfragen.abfrage_delete, name="abfrage_delete"),
    path("cluster/", abfragen.cluster, name="cluster"),
    path("tenants/<int:pk>/", tenant.tenant_detail, name="tenant_detail"),
    path("tenants/<int:pk>/enrollment-proof/upload/", enrollment_proof.upload_proof, name="enrollment_proof_upload"),
    path("tenants/<int:pk>/enrollment-proof/<int:proof_pk>/verify/", enrollment_proof.verify_proof, name="enrollment_proof_verify"),
    path("tenants/<int:pk>/enrollment-proof/<int:proof_pk>/revert/", enrollment_proof.revert_proof, name="enrollment_proof_revert"),
    path("tenants/<int:pk>/enrollment-proof/<int:proof_pk>/reject/", enrollment_proof.reject_proof, name="enrollment_proof_reject"),
    path("tenants/<int:pk>/enrollment-proof/<int:proof_pk>/edit/", enrollment_proof.edit_proof, name="enrollment_proof_edit"),
    path("tenants/<int:pk>/enrollment-proof/<int:proof_pk>/download/", enrollment_proof.download_proof, name="enrollment_proof_download"),
    path("notes/add/", notes.add_note, name="note_add"),
    path("notes/<int:pk>/delete/", notes.delete_note, name="note_delete"),
    path("admin/", admin_views.admin_portal, name="admin_portal"),
    path("admin/sync-from-ldap/", admin_views.sync_from_ldap, name="sync_from_ldap"),
    path("admin/permissions/", admin_views.permission_matrix, name="permission_matrix"),
]
