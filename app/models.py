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


class NoteSubjectType(models.TextChoices):
    TENANT = "tenant", "Bewohner:in"
    CLUSTER = "cluster", "Cluster"
    WG = "wg", "WG"


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
