"""One-off import of Briefkasten opt-ins from the old abfrage.ca-hd.de CSV export."""

import csv

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from app.models import Tenant


class Command(BaseCommand):
    help = "Set mailbox_list_opt_in from user_preferences.csv (username,mailbox_name,...)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, csv_path, dry_run, **options):
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('cartei.changed_by', %s, true)", ["abfrage_import"])
                cursor.execute("SELECT set_config('cartei.change_source', %s, true)", ["IMPORT"])

        tenants = {t.intranet_username.lower(): t for t in Tenant.objects.exclude(intranet_username=None)}
        updated, skipped, missing, answered = 0, 0, [], set()
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["mailbox_name"] not in ("0", "1"):
                    continue
                tenant = tenants.get(row["username"].strip().lower())
                if tenant is None:
                    missing.append(row["username"])
                    continue
                answered.add(tenant.pk)
                # An answer given in CArtei is newer than the old site's; keep it.
                if tenant.profile_setup_completed_at:
                    skipped += 1
                    continue
                opt_in = row["mailbox_name"] == "1"
                if tenant.mailbox_list_opt_in != opt_in:
                    tenant.mailbox_list_opt_in = opt_in
                    tenant.save(update_fields=["mailbox_list_opt_in"])
                    updated += 1

        # The mailbox list trusts every "yes"; one that neither CArtei nor the CSV confirms is legacy data.
        reset = 0
        for tenant in Tenant.objects.filter(
            mailbox_list_opt_in=True, profile_setup_completed_at=None,
        ).exclude(pk__in=answered):
            tenant.mailbox_list_opt_in = False
            tenant.save(update_fields=["mailbox_list_opt_in"])
            reset += 1

        self.stdout.write(
            f"updated {updated}, kept CArtei answer {skipped}, reset unconfirmed yes {reset}, unknown {len(missing)}"
        )
        for username in missing:
            self.stdout.write(f"  unknown: {username}")
        if dry_run:
            transaction.set_rollback(True)
            self.stdout.write("dry run, rolled back")
