import uuid as uuid_module

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from app import ldap_utils
from app.decorators import require_group
from app.models import Tenant


@require_POST
@require_group("admins")
def sync_from_ldap(request):
    """Bulk-sync all confidentiality_clearance LDAP members to Tenant records."""
    members = ldap_utils.get_clearance_members()
    created = updated = 0
    for m in members:
        try:
            intranet_uuid = uuid_module.UUID(m["uuid"]) if m["uuid"] else uuid_module.uuid4()
        except ValueError:
            intranet_uuid = uuid_module.uuid4()

        tenant, was_created = Tenant.objects.get_or_create(
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
        else:
            Tenant.objects.filter(pk=tenant.pk).update(
                first_name=m["first_name"],
                last_name=m["last_name"],
                email=m["email"],
                intranet_uuid=intranet_uuid,
            )
            updated += 1

    return JsonResponse({"created": created, "updated": updated})
