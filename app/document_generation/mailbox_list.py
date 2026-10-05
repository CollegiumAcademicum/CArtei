"""Feed current CArtei data to the existing Briefkastenliste script."""

import csv
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from app.models import TenantRoomAssignment
from app.residency import assignment_active_on


class NoMailboxResidents(Exception):
    """No current Neubau resident opted in to the list."""


class MailboxListGenerationError(Exception):
    """The CSV input or the external PDF toolchain failed."""


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
        if tenant.mailbox_list_opt_in:
            room_parts = room_name.split(".")
            if (
                not tenant.first_name.strip()
                or not tenant.last_name.strip()
                or not any(ch.isupper() for ch in tenant.last_name)
                or len(room_parts) < 3
                or ".".join(room_parts[:2]) != assignment.room.wg.name
            ):
                raise MailboxListGenerationError("Incomplete resident or room data")
        row = by_tenant.get(tenant.pk)
        if row is None:
            by_tenant[tenant.pk] = {
                "id": f"tenant-{tenant.pk}",  # string prefix keeps pandas' .str operations valid
                "forename": tenant.first_name,
                "surename": tenant.last_name,
                "flatnumber": room_name,
                "opt_in": tenant.mailbox_list_opt_in,
            }
        else:
            row["flatnumber"] = f"{row['flatnumber']} und {room_name}"
    return list(by_tenant.values())


def generate_mailbox_list(today):
    rows = resident_rows(today)
    if not any(row["opt_in"] for row in rows):
        raise NoMailboxResidents

    with tempfile.TemporaryDirectory(prefix="cartei-briefkastenliste-") as directory:
        directory = Path(directory)
        residents_csv = directory / "residents.csv"
        mask_csv = directory / "preferences.csv"
        pdf_file = directory / "briefkastenliste.pdf"
        imposed_pdf = directory / "briefkastenliste-pdfjam.pdf"

        with residents_csv.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(("id", "forename", "surename", "flatnumber"))
            writer.writerows((r["id"], r["forename"], r["surename"], r["flatnumber"]) for r in rows)
        with mask_csv.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(("username", "mailbox_name"))
            writer.writerows((r["id"], r["opt_in"]) for r in rows)

        command = [
            sys.executable, str(Path(__file__).with_name("create_briefkastenliste.py")),
            "--mask_csv", str(mask_csv), "--mask_id", "username",
            "--mask_val", "mailbox_name", "-o", str(pdf_file),
            str(residents_csv),
        ]
        try:
            subprocess.run(
                command, cwd=directory, env={**os.environ, "TZ": "Europe/Berlin"},
                capture_output=True, text=True, check=True, timeout=25,
            )
            if not imposed_pdf.is_file() or imposed_pdf.stat().st_size == 0:
                raise MailboxListGenerationError("No imposed PDF was produced")
            return imposed_pdf.read_bytes()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise MailboxListGenerationError("Briefkastenliste generation failed") from exc
