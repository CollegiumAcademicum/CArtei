"""Nightly: warn when a linked tenant's FreeIPA mail drifted from the DB (SSOT).

Happens when a directory admin edits `mail` in FreeIPA directly, bypassing
CArtei (tenants can't — self-service on the mail attribute is locked). Reports
only; correcting drift is a human decision. Wire to a systemd timer.
"""
from django.core.management.base import BaseCommand

from app.ldap_utils import find_email_drift


class Command(BaseCommand):
    help = "Report tenants whose FreeIPA mail differs from the DB email (SSOT)."

    def handle(self, *args, **options):
        drift = find_email_drift()
        if not drift:
            self.stdout.write("No email drift.")
            return
        for d in drift:
            ldap = d["ldap_email"] or "<no LDAP entry>"
            self.stderr.write(
                f"DRIFT {d['uid']}: db={d['db_email']!r} ldap={ldap!r}"
            )
        self.stderr.write(f"{len(drift)} tenant(s) drifted.")
