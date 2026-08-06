import uuid as uuid_module

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from app import ldap_utils
from app.decorators import require_group
from app.models import Tenant


@require_group("admins")
def admin_portal(request):
    total = Tenant.objects.count()
    flinta = Tenant.objects.filter(is_flinta=True).count()
    azubi = Tenant.objects.filter(apprenticeship_field__isnull=False).exclude(apprenticeship_field="").count()
    return render(request, "app/admin/portal.html", {
        "total": total,
        "flinta_quote": round(flinta / total * 100, 1) if total else 0,
        "azubi_quote": round(azubi / total * 100, 1) if total else 0,
    })


@require_POST
@require_group("admins")
def sync_from_ldap(request):
    """Import new LDAP members as Tenants; never overwrites existing records."""
    members = ldap_utils.get_clearance_members()
    created = 0
    for m in members:
        try:
            intranet_uuid = uuid_module.UUID(m["uuid"]) if m["uuid"] else uuid_module.uuid4()
        except ValueError:
            intranet_uuid = uuid_module.uuid4()
        _, was_created = Tenant.objects.get_or_create(
            intranet_username=m["username"],
            defaults={
                "intranet_uuid": intranet_uuid,
                "first_name": m["first_name"],
                "last_name": m["last_name"],
                "email": m["email"],
            },
        )
        if was_created:
            created += 1
    messages.success(request, f"Sync abgeschlossen: {created} neue Mieter*innen angelegt.")
    return redirect("admin_portal")
