from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app.models import (
    Tenant, TenantRoomAssignment, UebergabeProtokoll, UebergabeProtokollDamage,
    UebergabeProtokollType,
)
from app.tenant_access import global_roles
from app.uebergabe_steps import protocol_lines

UEBERGABE_ROLES = {"mietverwaltung", "admin", "mietverwaltung_helfer"}


def can_do_uebergabe(user):
    return bool(UEBERGABE_ROLES & global_roles(user))


def _caller(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


@login_required
@require_POST
def uebergabe_start(request, assignment_pk, protocol_type):
    if not can_do_uebergabe(request.user):
        raise PermissionDenied
    if protocol_type not in UebergabeProtokollType.values:
        return HttpResponseBadRequest()
    assignment = get_object_or_404(TenantRoomAssignment, pk=assignment_pk)
    p = UebergabeProtokoll.objects.create(
        assignment=assignment, protocol_type=protocol_type, created_at=now(),
    )
    UebergabeProtokollDamage.objects.bulk_create(
        [UebergabeProtokollDamage(protocol=p, line=line) for line in protocol_lines()]
    )
    return redirect("uebergabe_step", pk=p.pk, step=0)


@login_required
def uebergabe_step(request, pk, step):
    return HttpResponse("")  # implemented in Task 9
