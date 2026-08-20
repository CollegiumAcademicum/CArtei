from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.forms import modelform_factory, modelformset_factory
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app.models import (
    Tenant, TenantRoomAssignment, UebergabeProtokoll, UebergabeProtokollDamage,
    UebergabeProtokollType,
)
from app.tenant_access import global_roles
from app.uebergabe_steps import BUCKETS, DAMAGE_META, STEPS, protocol_lines

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


def _header_form_cls(fields):
    return modelform_factory(UebergabeProtokoll, fields=fields)


_DamageFormSet = modelformset_factory(
    UebergabeProtokollDamage, fields=["count_lt1", "count_mid", "count_gt", "note"], extra=0,
)


@login_required
def uebergabe_step(request, pk, step):
    if not can_do_uebergabe(request.user):
        raise PermissionDenied
    p = get_object_or_404(UebergabeProtokoll, pk=pk)
    if not 0 <= step < len(STEPS):
        return HttpResponseBadRequest()
    cfg = STEPS[step]
    header_fields = cfg.get("header", [])
    line_values = cfg.get("lines", [])
    damage_qs = p.damages.filter(line__in=line_values).order_by("line") if line_values else p.damages.none()

    if request.method == "POST":
        hform = _header_form_cls(header_fields)(request.POST, instance=p) if header_fields else None
        fset = _DamageFormSet(request.POST, queryset=damage_qs) if line_values else None
        ok = (hform is None or hform.is_valid()) and (fset is None or fset.is_valid())
        if ok:
            if hform is not None:
                hform.save()
            if fset is not None:
                fset.save()
            delta = 1 if request.POST.get("direction") == "weiter" else -1
            nxt = min(max(step + delta, 0), len(STEPS) - 1)
            return redirect("uebergabe_step", pk=p.pk, step=nxt)
    else:
        hform = _header_form_cls(header_fields)(instance=p) if header_fields else None
        fset = _DamageFormSet(queryset=damage_qs) if line_values else None

    damage_rows = []
    if fset is not None:
        for form in fset:
            label, kind = DAMAGE_META[form.instance.line]
            damage_rows.append({"form": form, "label": label, "buckets": BUCKETS[kind]})

    return render(request, "app/uebergabe/step.html", {
        "protocol": p, "assignment": p.assignment, "step": step, "steps": STEPS,
        "cfg": cfg, "hform": hform, "fset": fset, "damage_rows": damage_rows,
        "is_last": step == len(STEPS) - 1,
    })
