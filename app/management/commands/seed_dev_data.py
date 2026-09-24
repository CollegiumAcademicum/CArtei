"""Populate an isolated local database with synthetic, linked example records."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.contrib.sessions.backends.db import SessionStore
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from weasyprint import HTML

from app.models import (
    AGAbfrage, AGAbfrageHealth, AGAbfrageResult, AGHealth, AGStatus,
    BescheidAusbildungsstelleDocument, Building, DamageSize,
    DatenschutzDocument, DocumentSigner, DocumentType, EnrollmentProof,
    EnrollmentType, InternalNote, MietbedingungenDocument, MietvertragDocument,
    NoteSourceGroup, NoteSubjectType, PhotoerlaubnisDocument, Room,
    RoomDamage, RoomDamageLine, SelbstverpflichtungEngagementDocument,
    SepaLastschriftmandatDocument, Tenant, TenantRoomAssignment,
    UserSession, VertraulichkeitserklaerungDocument, WG, WGDamage,
    WGDamageLine, WohnungsgeberbescheinigungDocument,
)


PASSWORD = "cartei-dev"
PEOPLE = [
    ("Ada", "Beispiel"), ("Ben", "Muster"), ("Cora", "Albrecht"),
    ("Dario", "Brandt"), ("Eleni", "Dietrich"), ("Fatima", "Engel"),
    ("Gino", "Falk"), ("Hanna", "Grün"), ("Ivo", "Hartmann"),
    ("Jana", "Ibrahim"), ("Kian", "Jäger"), ("Lena", "Keller"),
    ("Mika", "Lorenz"), ("Nora", "Müller"), ("Omar", "Neumann"),
    ("Pia", "Özdemir"), ("Quinn", "Peters"), ("Rita", "Richter"),
    ("Sami", "Schulz"), ("Tara", "von Stein"), ("Uli", "Ulrich"),
    ("Vera", "Vogel"), ("Willi", "Weber"), ("Zara", "Zimmer"),
]
ROLE_USERS = {
    0: ("dev_admin", "admin"),
    1: ("dev_mv", "mietverwaltung"),
    2: ("dev_cluster", "cluster"),
    3: ("dev_belegium", "belegium"),
    4: ("dev_helper", "mietverwaltung_helfer"),
    5: ("dev_werkstatt", "werkstatt"),
    6: ("dev_finance", "finanzierung"),
    7: ("dev_resident", None),
}


class Command(BaseCommand):
    help = "Seed the isolated local development database; never runs in production."

    def handle(self, *args, **options):
        if not getattr(settings, "DEV_SEED_ENABLED", False) or not settings.DEBUG:
            raise CommandError("seed_dev_data requires cartei.settings_dev.")
        if connection.vendor != "postgresql":
            raise CommandError("seed_dev_data requires the migrated PostgreSQL database.")
        if not settings.DEV_SUPERUSER_PASSWORD:
            raise CommandError("DEV_SUPERUSER_PASSWORD must not be empty.")

        with transaction.atomic():
            if Tenant.objects.filter(intranet_username="dev_admin").exists():
                self._ensure_superuser()
                self.stdout.write("Development data already exists; superuser available.")
                return
            self._seed()
            self._ensure_superuser()
        self.stdout.write(self.style.SUCCESS("Development data created. Other demo accounts use password: cartei-dev"))

    def _ensure_superuser(self):
        username = "dev_superuser"
        tenant, _ = Tenant.objects.get_or_create(
            intranet_username=username,
            defaults={
                "first_name": "Sophie",
                "last_name": "Superuser",
                "email": "dev-superuser@example.invalid",
                "intranet_uuid": UUID(int=25),
                "mailbox_list_opt_in": False,
            },
        )
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": tenant.first_name,
                "last_name": tenant.last_name,
                "email": tenant.email,
            },
        )
        fields = []
        if created or not user.check_password(settings.DEV_SUPERUSER_PASSWORD):
            user.set_password(settings.DEV_SUPERUSER_PASSWORD)
            fields.append("password")
        for field in ("is_staff", "is_superuser", "is_active"):
            if not getattr(user, field):
                setattr(user, field, True)
                fields.append(field)
        if fields:
            user.save(update_fields=fields)
        user.groups.add(Group.objects.get_or_create(
            name=settings.TENANT_ROLE_GROUPS["admin"][0],
        )[0])

    def _seed(self):
        now = timezone.now()
        today = timezone.localdate()
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('cartei.changed_by', %s, true)", ["dev_seed"])
            cursor.execute("SELECT set_config('cartei.change_source', %s, true)", ["SEED"])

        tenants = []
        for i, (first, last) in enumerate(PEOPLE):
            username = ROLE_USERS[i][0] if i in ROLE_USERS else (None if i == 23 else f"dev_person_{i:02d}")
            tenant = Tenant.objects.create(
                first_name=first, last_name=last,
                email=f"dev-person-{i:02d}@example.invalid",
                intranet_username=username,
                intranet_uuid=UUID(int=i + 1) if username else None,
                preferred_name=first if i % 5 == 0 else None,
                pronouns="sie/ihr" if i % 3 == 0 else None,
                date_of_birth=today - timedelta(days=365 * (20 + i % 15)),
                phone=f"+49 000 000 {i:03d}",
                is_flinta=i % 2 == 0,
                barrier_free_needed=i == 11,
                mailbox_list_opt_in=i % 4 != 0,
                soli_miete_wunsch=Decimal("250.00") + i,
            )
            tenants.append(tenant)

        for i, (username, role) in ROLE_USERS.items():
            user = User.objects.create_user(
                username=username, password=PASSWORD,
                first_name=PEOPLE[i][0], last_name=PEOPLE[i][1],
                email=tenants[i].email,
            )
            if role:
                group_name = settings.TENANT_ROLE_GROUPS[role][0]
                user.groups.add(Group.objects.get_or_create(name=group_name)[0])
        tenants[2].comments = "Nur synthetische Beispieldaten."
        tenants[2].save(update_fields=["comments"])  # create an entity_history row

        neubau = Building.objects.get(name="Neubau")
        altbau = Building.objects.get(name="Altbau")
        nb_rooms = list(Room.objects.filter(wg__building=neubau).select_related("wg").order_by("name"))
        ab_room = Room.objects.filter(wg__building=altbau).select_related("wg").first()
        if len(nb_rooms) < len(tenants) or ab_room is None:
            raise CommandError("Expected migrated Neubau and Altbau room seeds.")
        nb_rooms[0].size_sqm = Decimal("12.50")
        nb_rooms[0].has_bed = True
        nb_rooms[0].save(update_fields=["size_sqm", "has_bed"])

        assignments = []
        for i, tenant in enumerate(tenants):
            if i == 23:  # tenant added manually, still waiting for a room
                continue
            if i == 21:  # former resident
                moved_in, moved_out = today - timedelta(days=400), today - timedelta(days=20)
            elif i == 22:  # future resident
                moved_in, moved_out = today + timedelta(days=20), None
            else:
                moved_in, moved_out = today - timedelta(days=180 + i), None
            room = ab_room if i == 20 else nb_rooms[i]
            assignments.append(TenantRoomAssignment.objects.create(
                tenant=tenant, room=room, moved_in=moved_in, moved_out=moved_out,
                mailbox_key_received=moved_in if i % 3 == 0 else None,
                mailbox_key_returned=moved_out if i == 21 else None,
                is_sublet=i == 19,
                sublet_of_tenant=tenants[18] if i == 19 else None,
                key_received=moved_in if i % 2 == 0 else None,
                key_returned=moved_out if i == 21 else None,
                deposit_iban="DE00 0000 0000 0000 0000 00" if i == 1 else None,
            ))

        surveys = [
            AGAbfrage.objects.create(date=today, label="Aktuelle Demo-Abfrage", ends_at=today + timedelta(days=14), grace_ends_at=today + timedelta(days=19)),
            AGAbfrage.objects.create(date=today - timedelta(days=16), label="Demo-Nachfrist", ends_at=today - timedelta(days=2), grace_ends_at=today + timedelta(days=3)),
            AGAbfrage.objects.create(date=today - timedelta(days=60), label="Vergangene Demo-Abfrage", ends_at=today - timedelta(days=46), grace_ends_at=today - timedelta(days=41)),
        ]
        for survey, health in zip(surveys, (AGHealth.GESUND, AGHealth.KRITISCH, AGHealth.TOT)):
            AGAbfrageHealth.objects.create(abfrage=survey, ag_name="ag.demo", health=health, note="Synthetische Abfrage")
        for i, status in enumerate((AGStatus.AKTIV, AGStatus.INAKTIV, AGStatus.IM_GESPRAECH, AGStatus.ZU_AKTIV, AGStatus.NICHT_AUSREICHEND)):
            AGAbfrageResult.objects.create(abfrage=surveys[0], ag_name="ag.demo", tenant=tenants[i], status=status)

        pdf = HTML(string="<h1>Demo-Dokument</h1><p>Nur synthetische Daten.</p>").write_pdf()
        for i, values in enumerate((
            {"verified_by": None, "verified_at": None},
            {"verified_by": tenants[1], "verified_at": now - timedelta(days=2)},
            {"verified_by": None, "verified_at": None, "needs_human_review": True, "review_reason": "Demo: manuelle Prüfung"},
        )):
            EnrollmentProof.objects.create(
                tenant=tenants[i], enrollment_type=(EnrollmentType.STUDY, EnrollmentType.APPRENTICESHIP, EnrollmentType.FSJ)[i],
                field_of_study="Demofach" if i == 0 else None,
                educational_institution="Demo-Institut", file_name=f"demo-nachweis-{i}.pdf",
                file_data=pdf, uploaded_at=now - timedelta(days=3 + i), uploaded_by=tenants[i],
                valid_until=today + timedelta(days=90), **values,
            )

        documents = {}
        common = {"tenant": tenants[7], "file_data": pdf, "uploaded_at": now, "uploaded_by": tenants[1], "signed_at": today}
        for kind, model in (
            (DocumentType.DATENSCHUTZ, DatenschutzDocument),
            (DocumentType.PHOTOERLAUBNIS, PhotoerlaubnisDocument),
            (DocumentType.VERTRAULICHKEITSERKLAERUNG, VertraulichkeitserklaerungDocument),
            (DocumentType.MIETBEDINGUNGEN, MietbedingungenDocument),
            (DocumentType.SELBSTVERPFLICHTUNG_ENGAGEMENT, SelbstverpflichtungEngagementDocument),
        ):
            documents[kind] = model.objects.create(file_name=f"demo-{kind}.pdf", **common)
        MietvertragDocument.objects.create(
            tenant=tenants[7], file_name="demo-mietvertrag.pdf", file_data=pdf,
            uploaded_at=now, uploaded_by=tenants[1], renter_signed_at=today,
            company_signed_at=today, company_signed_by=tenants[1],
        )
        SepaLastschriftmandatDocument.objects.create(
            file_name="demo-sepa.pdf", mandatsreferenz="DEMO-1", kontoinhaber="Demo Person",
            bank_name="Demo Bank", iban="DE00 0000 0000 0000 0000 00", bic="DEMODE00XXX", **common,
        )
        BescheidAusbildungsstelleDocument.objects.create(
            file_name="demo-bescheid.pdf", signed_by=tenants[1], **common,
        )
        WohnungsgeberbescheinigungDocument.objects.create(
            assignment=assignments[7], file_name="demo-wohnungsgeber.pdf", file_data=pdf,
            uploaded_at=now, uploaded_by=tenants[1], signed_at=today,
            company_signed_by=tenants[1],
        )
        DocumentSigner.objects.create(
            document_type=DocumentType.DATENSCHUTZ,
            document_id=documents[DocumentType.DATENSCHUTZ].pk, tenant=tenants[7],
        )
        DatenschutzDocument.objects.filter(pk=documents[DocumentType.DATENSCHUTZ].pk).update(
            revoked_at=now, revoked_by=tenants[1], revoked_note="Demo: ersetzt",
        )

        InternalNote.objects.create(
            body="Demo-Notiz der Mietverwaltung", source_group=NoteSourceGroup.MIETVERWALTUNG,
            subject_type=NoteSubjectType.TENANT, subject_id=tenants[7].pk,
            created_at=now, created_by=tenants[1],
        )
        InternalNote.objects.create(
            body="Demo-Belegungsnotiz", source_group=NoteSourceGroup.BELEGUNG,
            subject_type=NoteSubjectType.ROOM_ASSIGNMENT, subject_id=assignments[7].pk,
            created_at=now - timedelta(days=3), created_by=tenants[3],
            deleted_at=now, deleted_by=tenants[3],
        )
        InternalNote.objects.create(
            body="Demo-Cluster-Notiz", source_group=NoteSourceGroup.CLUSTERSPRECHENDE,
            subject_type=NoteSubjectType.TENANT, subject_id=tenants[8].pk,
            created_at=now, created_by=tenants[2],
        )
        RoomDamage.objects.create(
            room=nb_rooms[7], line=RoomDamageLine.WAND_FLECKEN, size=DamageSize.MID,
            note="Synthetischer Fleck", created_at=now, created_by=tenants[3],
        )
        RoomDamage.objects.create(
            room=nb_rooms[8], line=RoomDamageLine.BODEN_LOECHER, size=DamageSize.LT1,
            note="Synthetisch behoben", created_at=now - timedelta(days=4),
            created_by=tenants[3], fixed_at=now, fixed_by=tenants[3],
        )
        WGDamage.objects.create(
            wg=nb_rooms[7].wg, line=WGDamageLine.KUECHE_FLECK, size=DamageSize.GT,
            note="Synthetischer Schaden", created_at=now, created_by=tenants[3],
        )

        user = User.objects.get(username="dev_admin")
        session = SessionStore()
        session["_auth_user_id"] = str(user.pk)
        session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
        session["_auth_user_hash"] = user.get_session_auth_hash()
        session.save()
        UserSession.objects.create(
            session_key=session.session_key, username=user.username,
            ip_address="127.0.0.1", user_agent="Synthetic development session", created_at=now,
        )
