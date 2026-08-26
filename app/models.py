from decimal import Decimal

from django.db import models


class AGStatus(models.TextChoices):
    ZU_AKTIV = "ZU_AKTIV", "zu aktiv"
    AKTIV = "AKTIV", "aktiv"
    NICHT_AUSREICHEND = "NICHT_AUSREICHEND", "nicht ausreichend"
    IM_GESPRAECH = "IM_GESPRAECH", "im Gespräch"
    INAKTIV = "INAKTIV", "inaktiv"


class AGHealth(models.TextChoices):
    GESUND = "GESUND", "gesund"
    KERNAUFGABEN = "KERNAUFGABEN", "nur Kernaufgaben"
    KRITISCH = "KRITISCH", "kritisch"
    TOT = "TOT", "tot"


class NoteSourceGroup(models.TextChoices):
    MIETVERWALTUNG = "mietverwaltung", "Mietverwaltung"
    CLUSTERSPRECHENDE = "clustersprechende", "Clustersprechende"
    # Shared thread on room assignments — written by Mietverwaltung *and* Belegium.
    BELEGUNG = "belegung", "Belegung"


class NoteSubjectType(models.TextChoices):
    TENANT = "tenant", "Bewohner:in"
    CLUSTER = "cluster", "Cluster"
    WG = "wg", "WG"
    ROOM_ASSIGNMENT = "room_assignment", "Zimmerbelegung"


class Tenant(models.Model):
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    email = models.CharField(max_length=255, default="")
    intranet_username = models.CharField(max_length=255, unique=True)
    intranet_uuid = models.UUIDField(unique=True)
    preferred_name = models.CharField(max_length=255, null=True, blank=True)
    pronouns = models.CharField(max_length=255, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    is_flinta = models.BooleanField(default=False)
    barrier_free_needed = models.BooleanField(default=False)
    mailbox_list_opt_in = models.BooleanField(default=False)
    soli_miete_wunsch = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    comments = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "tenant"

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} ({self.intranet_username})"


class AGAbfrage(models.Model):
    date = models.DateField()
    label = models.CharField(max_length=255, null=True, blank=True)
    ends_at = models.DateField()
    grace_ends_at = models.DateField()

    class Meta:
        managed = False
        db_table = "ag_abfrage"
        ordering = ["-date"]

    def __str__(self) -> str:
        return self.label or f"Abfrage {self.ends_at}"

    @property
    def state(self) -> str:
        from datetime import date
        today = date.today()
        if today <= self.ends_at:
            return "open"
        if today <= self.grace_ends_at:
            return "grace"
        return "closed"

    @property
    def user_state(self) -> str:
        return "open" if self.state in ("open", "grace") else "closed"

    def can_ag_edit(self) -> bool:
        return self.state in ("open", "grace")


class AGAbfrageResult(models.Model):
    abfrage = models.ForeignKey(AGAbfrage, on_delete=models.DO_NOTHING, db_constraint=False)
    ag_name = models.CharField(max_length=255)
    tenant = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False)
    status = models.CharField(max_length=50, choices=AGStatus.choices)
    note = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "ag_abfrage_result"


class AGAbfrageHealth(models.Model):
    abfrage = models.ForeignKey(AGAbfrage, on_delete=models.DO_NOTHING, db_constraint=False)
    ag_name = models.CharField(max_length=255)
    health = models.CharField(max_length=50, choices=AGHealth.choices)
    note = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "ag_abfrage_health"


class InternalNote(models.Model):
    body = models.TextField()
    source_group = models.CharField(max_length=50, choices=NoteSourceGroup.choices)
    subject_type = models.CharField(max_length=50, choices=NoteSubjectType.choices)
    subject_id = models.IntegerField()
    created_at = models.DateTimeField()
    created_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+"
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False,
        null=True, blank=True, related_name="+"
    )

    class Meta:
        managed = False
        db_table = "internal_note"


class Building(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        managed = False
        db_table = "building"

    def __str__(self) -> str:
        return self.name


class WG(models.Model):
    building = models.ForeignKey(Building, on_delete=models.DO_NOTHING, db_constraint=False)
    name = models.CharField(max_length=255)
    cluster = models.CharField(max_length=3, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "wg"

    def __str__(self) -> str:
        return self.name


class Room(models.Model):
    wg = models.ForeignKey(WG, on_delete=models.DO_NOTHING, db_constraint=False)
    name = models.CharField(max_length=255)
    size_sqm = models.DecimalField(max_digits=8, decimal_places=2)
    has_mattress = models.BooleanField(default=False)
    has_bed = models.BooleanField(default=False)
    has_table = models.BooleanField(default=False)
    has_closet = models.BooleanField(default=False)
    freifinanziert = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = "room"

    def __str__(self) -> str:
        return self.name


class TenantRoomAssignment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False)
    room = models.ForeignKey(Room, on_delete=models.DO_NOTHING, db_constraint=False)
    moved_in = models.DateField()
    moved_out = models.DateField(null=True, blank=True)
    mailbox_key_received = models.DateField(null=True, blank=True)
    mailbox_key_returned = models.DateField(null=True, blank=True)
    is_sublet = models.BooleanField(default=False)
    sublet_of_tenant = models.ForeignKey(
        Tenant, null=True, blank=True, on_delete=models.DO_NOTHING,
        db_constraint=False, related_name="+",
    )
    key_received = models.DateField(null=True, blank=True)
    key_returned = models.DateField(null=True, blank=True)
    deposit_iban = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "tenant_room_assignment"


class EnrollmentType(models.TextChoices):
    STUDY = "STUDY", "Studium"
    APPRENTICESHIP = "APPRENTICESHIP", "Ausbildung"
    SCHUELER = "SCHUELER", "Schüler*in"
    FSJ = "FSJ", "Freiwilliges Soziales Jahr"


class EnrollmentProof(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False, related_name="enrollment_proofs")
    enrollment_type = models.CharField(max_length=50, choices=EnrollmentType.choices)
    field_of_study = models.CharField(max_length=255, null=True, blank=True)
    educational_institution = models.CharField(max_length=255, null=True, blank=True)
    file_name = models.CharField(max_length=255)
    file_data = models.BinaryField()
    uploaded_at = models.DateTimeField()
    uploaded_by = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True, related_name="uploaded_proofs", db_column="uploaded_by_id")
    last_edited_at = models.DateTimeField(null=True, blank=True)
    last_edited_by = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True, related_name="edited_proofs", db_column="last_edited_by_id")
    valid_until = models.DateField()
    verified_by = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True, related_name="verified_proofs", db_column="verified_by_id")
    verified_at = models.DateTimeField(null=True, blank=True)
    needs_human_review = models.BooleanField(default=False)
    review_reason = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "enrollment_proof"


class DocumentType(models.TextChoices):
    DATENSCHUTZ = "datenschutz", "Datenschutz"
    PHOTOERLAUBNIS = "photoerlaubnis", "Fotoerlaubnis"
    VERTRAULICHKEITSERKLAERUNG = "vertraulichkeitserklaerung", "Vertraulichkeitserklärung"


class DocumentBase(models.Model):
    """Shared columns for every per-type document mirror. Abstract — each
    concrete subclass maps its own managed=False table."""
    tenant = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False, related_name="%(class)ss")
    file_name = models.CharField(max_length=255)
    file_data = models.BinaryField()
    signed_at = models.DateField()
    uploaded_at = models.DateTimeField()
    uploaded_by = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False, related_name="%(class)s_uploaded", db_column="uploaded_by_id")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True, related_name="%(class)s_revoked", db_column="revoked_by_id")
    revoked_note = models.TextField(null=True, blank=True)

    class Meta:
        abstract = True


class DatenschutzDocument(DocumentBase):
    class Meta:
        managed = False
        db_table = "datenschutz_document"


class PhotoerlaubnisDocument(DocumentBase):
    class Meta:
        managed = False
        db_table = "photoerlaubnis_document"


class VertraulichkeitserklaerungDocument(DocumentBase):
    class Meta:
        managed = False
        db_table = "vertraulichkeitserklaerung_document"


# document_type value -> mirror model. Single source for views/templates.
DOCUMENT_MODELS = {
    DocumentType.DATENSCHUTZ.value: DatenschutzDocument,
    DocumentType.PHOTOERLAUBNIS.value: PhotoerlaubnisDocument,
    DocumentType.VERTRAULICHKEITSERKLAERUNG.value: VertraulichkeitserklaerungDocument,
}


class DocumentSigner(models.Model):
    """Polymorphic signer shared across the per-type document tables
    (mirrors cartei_db: document_type + document_id, no FK)."""
    document_type = models.CharField(max_length=50, choices=DocumentType.choices)
    document_id = models.IntegerField()
    tenant = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False, related_name="signed_documents")

    class Meta:
        managed = False
        db_table = "document_signer"


class AssignmentDocumentType(models.TextChoices):
    MIETVERTRAG = "mietvertrag", "Mietvertrag"
    MIETBEDINGUNGEN = "mietbedingungen", "Allgemeine Mietbedingungen"
    WOHNUNGSGEBERBESCHEINIGUNG = "wohnungsgeberbescheinigung", "Wohnungsgeberbescheinigung"


class RoomAssignmentDocumentBase(models.Model):
    """Shared columns for every per-type room-assignment document mirror.
    Abstract — each concrete subclass maps its own managed=False table."""
    assignment = models.ForeignKey(
        TenantRoomAssignment, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="%(class)ss", db_column="tenant_room_assignment_id",
    )
    file_name = models.CharField(max_length=255)
    file_data = models.BinaryField()
    uploaded_at = models.DateTimeField()
    uploaded_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="%(class)s_uploaded", db_column="uploaded_by_id",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True,
        related_name="%(class)s_revoked", db_column="revoked_by_id",
    )
    revoked_note = models.TextField(null=True, blank=True)

    class Meta:
        abstract = True


class MietvertragDocument(RoomAssignmentDocumentBase):
    renter_signed_at = models.DateField()
    company_signed_at = models.DateField()
    company_signed_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="+", db_column="company_signed_by_id",
    )

    class Meta:
        managed = False
        db_table = "mietvertrag_document"


class MietbedingungenDocument(RoomAssignmentDocumentBase):
    signed_at = models.DateField()

    class Meta:
        managed = False
        db_table = "mietbedingungen_document"


class WohnungsgeberbescheinigungDocument(RoomAssignmentDocumentBase):
    signed_at = models.DateField()
    company_signed_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="+", db_column="company_signed_by_id",
    )

    class Meta:
        managed = False
        db_table = "wohnungsgeberbescheinigung_document"


ASSIGNMENT_DOCUMENT_MODELS = {
    AssignmentDocumentType.MIETVERTRAG.value: MietvertragDocument,
    AssignmentDocumentType.MIETBEDINGUNGEN.value: MietbedingungenDocument,
    AssignmentDocumentType.WOHNUNGSGEBERBESCHEINIGUNG.value: WohnungsgeberbescheinigungDocument,
}


class DamageSize(models.TextChoices):
    LT1 = "LT1", "< 1 cm"
    MID = "MID", "1–5 cm"
    GT = "GT", "> 5 cm"


class RoomDamageLine(models.TextChoices):
    BODEN_FLECKEN = "BODEN_FLECKEN", "Boden – Flecken"
    BODEN_LOECHER = "BODEN_LOECHER", "Boden – Löcher"
    FUSSLEISTE_FLECKEN = "FUSSLEISTE_FLECKEN", "Fußleiste – Flecken"
    WAND_FLECKEN = "WAND_FLECKEN", "Wände – Flecken"
    WAND_LOECHER = "WAND_LOECHER", "Wände – Löcher"
    WAND_KLEBER = "WAND_KLEBER", "Wände – Kleberückstände"
    TUER_FLECKEN = "TUER_FLECKEN", "Tür – Flecken"
    TUER_LOECHER = "TUER_LOECHER", "Tür – Löcher"
    FENSTER_RAHMEN_FLECKEN = "FENSTER_RAHMEN_FLECKEN", "Fenster – Flecken Rahmen"
    FENSTER_BANK_FLECKEN = "FENSTER_BANK_FLECKEN", "Fenster – Flecken Fensterbank"
    FENSTER_KLEBER = "FENSTER_KLEBER", "Fenster – Kleberückstände"
    BETT_FLECKEN = "BETT_FLECKEN", "Bett – Flecken"
    BETT_LOECHER = "BETT_LOECHER", "Bett – Löcher"
    MATRATZE_FLECKEN = "MATRATZE_FLECKEN", "Matratze – Flecken"
    SCHREIBTISCH_FLECKEN = "SCHREIBTISCH_FLECKEN", "Schreibtisch – Flecken"
    SCHREIBTISCH_LOECHER = "SCHREIBTISCH_LOECHER", "Schreibtisch – Löcher"
    SCHRANK_FLECKEN = "SCHRANK_FLECKEN", "Schrank – Flecken"
    SCHRANK_LOECHER = "SCHRANK_LOECHER", "Schrank – Löcher"
    SONSTIGES = "SONSTIGES", "Sonstiges"


class WGDamageLine(models.TextChoices):
    BAD_FLECK = "BAD_FLECK", "Bad – Fleck"
    BAD_LOCH = "BAD_LOCH", "Bad – Loch"
    BAD_KLEBER = "BAD_KLEBER", "Bad – Kleberückstände"
    BAD_SONSTIGES = "BAD_SONSTIGES", "Bad – Sonstiges"
    KUECHE_FLECK = "KUECHE_FLECK", "Küche – Fleck"
    KUECHE_LOCH = "KUECHE_LOCH", "Küche – Loch"
    KUECHE_KLEBER = "KUECHE_KLEBER", "Küche – Kleberückstände"
    KUECHE_SONSTIGES = "KUECHE_SONSTIGES", "Küche – Sonstiges"
    GEMEINSCHAFT_FLECK = "GEMEINSCHAFT_FLECK", "Gemeinschaftsfläche – Fleck"
    GEMEINSCHAFT_LOCH = "GEMEINSCHAFT_LOCH", "Gemeinschaftsfläche – Loch"
    GEMEINSCHAFT_KLEBER = "GEMEINSCHAFT_KLEBER", "Gemeinschaftsfläche – Kleberückstände"
    GEMEINSCHAFT_SONSTIGES = "GEMEINSCHAFT_SONSTIGES", "Gemeinschaftsfläche – Sonstiges"


class DamageBase(models.Model):
    size = models.CharField(max_length=8, choices=DamageSize.choices, null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField()
    created_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="+", db_column="created_by_id",
    )
    fixed_at = models.DateTimeField(null=True, blank=True)
    fixed_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True,
        related_name="+", db_column="fixed_by_id",
    )
    photo_name = models.TextField(null=True, blank=True)
    photo_data = models.BinaryField(null=True, blank=True)

    class Meta:
        abstract = True
        managed = False

    @property
    def is_open(self):
        return self.fixed_at is None

    @property
    def has_photo(self):
        return bool(self.photo_name)


class RoomDamage(DamageBase):
    room = models.ForeignKey(
        Room, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="damages", db_column="room_id",
    )
    line = models.CharField(max_length=32, choices=RoomDamageLine.choices)

    class Meta:
        managed = False
        db_table = "room_damage"


class WGDamage(DamageBase):
    wg = models.ForeignKey(
        WG, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="damages", db_column="wg_id",
    )
    line = models.CharField(max_length=32, choices=WGDamageLine.choices)

    class Meta:
        managed = False
        db_table = "wg_damage"


class UserSession(models.Model):
    """Mirror of cartei_db.user_session — login-time metadata for a Django web
    session. Identity is the LDAP/intranet username, matching Tenant.intranet_username."""
    session_key = models.CharField(max_length=40, unique=True)
    username = models.CharField(max_length=150)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "user_session"
