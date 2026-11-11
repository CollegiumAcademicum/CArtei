"""Build the Briefkastenliste PDF from current CArtei data (in-process)."""

import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

from app.document_generation.create_briefkastenliste import render_pdf
from app.models import Tenant, TenantRoomAssignment
from app.residency import assignment_active_on


class NoMailboxResidents(Exception):
    """No current Neubau resident opted in to the list."""


class MailboxListGenerationError(Exception):
    """The resident data or the external PDF toolchain (latexmk/pdfjam) failed."""


def resident_rows(today):
    """One row per tenant, joining all current Neubau rooms (e.g. "3.05 und 0.06")."""
    assignments = (
        TenantRoomAssignment.objects
        .filter(assignment_active_on(today), room__wg__building__name="Neubau")
        .select_related("tenant", "room__wg")
        .order_by("tenant_id", "-moved_in", "-pk")
    )
    by_tenant = {}
    seen_rooms = set()
    for assignment in assignments:
        tenant = assignment.tenant
        room_name = assignment.room.name
        if (tenant.pk, room_name) in seen_rooms:
            continue
        seen_rooms.add((tenant.pk, room_name))
        confirmed_opt_in = tenant.mailbox_list_opt_in
        if confirmed_opt_in:
            room_parts = room_name.split(".")
            if (
                not tenant.first_name.strip()
                or not tenant.last_name.strip()
                or not any(ch.isupper() for ch in tenant.last_name)
                or len(room_parts) < 3
                or ".".join(room_parts[:2]) != assignment.room.wg.name
            ):
                raise MailboxListGenerationError(
                    f"Unvollständige Daten für {tenant.first_name} {tenant.last_name} "
                    f"(Zimmer {room_name!r}) — Name oder Zimmernummer passt nicht zum erwarteten Format."
                )
        row = by_tenant.get(tenant.pk)
        if row is None:
            by_tenant[tenant.pk] = {
                "id": f"tenant-{tenant.pk}",  # string prefix keeps pandas' .str operations valid
                "forename": tenant.first_name,
                "surename": tenant.last_name,
                "flatnumber": room_name,
                "opt_in": confirmed_opt_in,
            }
        else:
            row["flatnumber"] = f"{row['flatnumber']} und {room_name}"
    if settings.BRIEFKASTENLISTE_IGNORE_ROOMS:
        # ponytail: rollout stopgap, opted-in tenants without any room assignment yet go on with an empty WG.
        unassigned = Tenant.objects.filter(mailbox_list_opt_in=True).exclude(
            pk__in=TenantRoomAssignment.objects.values("tenant_id"),
        )
        for tenant in unassigned:
            if not tenant.first_name.strip() or not any(ch.isupper() for ch in tenant.last_name):
                raise MailboxListGenerationError(
                    f"Unvollständige Daten für {tenant.first_name} {tenant.last_name} — Name passt nicht zum erwarteten Format."
                )
            by_tenant[tenant.pk] = {
                "id": f"tenant-{tenant.pk}",
                "forename": tenant.first_name,
                "surename": tenant.last_name,
                "flatnumber": "",
                "opt_in": True,
            }
    return list(by_tenant.values())


def generate_mailbox_list(today):
    rows = [row for row in resident_rows(today) if row["opt_in"]]
    if not rows:
        raise NoMailboxResidents

    with tempfile.TemporaryDirectory(prefix="cartei-briefkastenliste-") as directory:
        try:
            imposed_pdf = render_pdf(rows, directory, today)
            if not imposed_pdf.is_file() or imposed_pdf.stat().st_size == 0:
                raise MailboxListGenerationError("Es wurde kein PDF erzeugt (LaTeX/pdfjam lieferte keine Ausgabe).")
            return imposed_pdf.read_bytes()
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip().splitlines()
            tail = " ".join(detail[-3:]) if detail else "keine Ausgabe"
            raise MailboxListGenerationError(
                f"PDF-Werkzeug fehlgeschlagen (Exit {exc.returncode}): {tail}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise MailboxListGenerationError("PDF-Erzeugung hat das Zeitlimit überschritten.") from exc
        except OSError as exc:
            raise MailboxListGenerationError(f"PDF-Werkzeug nicht ausführbar: {exc}") from exc
