from decimal import Decimal

from django.db import models


class AGStatus(models.TextChoices):
    ZU_AKTIV = "ZU_AKTIV", "zu aktiv"
    AKTIV = "AKTIV", "aktiv"
    NICHT_AUSREICHEND = "NICHT_AUSREICHEND", "nicht ausreichend"
    IM_GESPRAECH = "IM_GESPRAECH", "im Gespräch"
    INAKTIV = "INAKTIV", "inaktiv"


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
    study_subject = models.CharField(max_length=255, null=True, blank=True)
    apprenticeship_field = models.CharField(max_length=255, null=True, blank=True)
    educational_institution = models.CharField(max_length=255, null=True, blank=True)
    barrier_free_needed = models.BooleanField(default=False)
    mailbox_key = models.BooleanField(default=False)
    mailbox_list_opt_in = models.BooleanField(default=False)
    soli_miete_wunsch = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    is_sublet = models.BooleanField(default=False)
    sublet_from = models.DateField(null=True, blank=True)
    sublet_to = models.DateField(null=True, blank=True)
    sublet_of_tenant = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.DO_NOTHING, db_constraint=False
    )
    data_priv_signed_at = models.DateField(null=True, blank=True)
    photo_allowance_signed_at = models.DateField(null=True, blank=True)
    move_in = models.DateField(null=True, blank=True)
    move_out = models.DateField(null=True, blank=True)
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


class ClusterNote(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False)
    abfrage = models.ForeignKey(AGAbfrage, on_delete=models.DO_NOTHING, db_constraint=False)
    note = models.TextField()
    created_at = models.DateTimeField()
    created_by = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = "cluster_note"
