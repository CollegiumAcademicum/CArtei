import datetime

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from app.models import (
    DatenschutzDocument, DocumentSigner, DocumentType,
    MietbedingungenDocument, MietvertragDocument, Tenant,
)


@pytest.fixture
def owner(db):
    # Documents are managed by Mietverwaltung only, so the acting user is MV.
    t = Tenant.objects.create(
        first_name="Owner", last_name="Self", email="o@example.com",
        intranet_username="owner_doc", intranet_uuid="00000000-0000-0000-0000-000000000010",
    )
    u = User.objects.create_user(username="owner_doc", password="x")
    u.groups.add(Group.objects.get_or_create(name="ag.mietverwaltung")[0])
    return t


def _login(client):
    client.login(username="owner_doc", password="x")


def _upload(client, tenant, **overrides):
    from django.core.files.uploadedfile import SimpleUploadedFile
    data = {
        "document_type": DocumentType.DATENSCHUTZ,
        "signed_at": "2026-08-01",
        "document_file": SimpleUploadedFile("d.pdf", b"%PDF-1.4 x", content_type="application/pdf"),
    }
    data.update(overrides)
    return client.post(reverse("document_upload", args=[tenant.pk]), data)


def test_upload_creates_document(client, owner):
    _login(client)
    _upload(client, owner)
    doc = DatenschutzDocument.objects.get(tenant=owner)
    assert doc.signed_at == datetime.date(2026, 8, 1)
    assert doc.uploaded_by_id == owner.pk
    assert doc.revoked_at is None
    # The signer is implicitly the tenant; document_signer is left unlinked.
    assert not DocumentSigner.objects.filter(
        document_type="datenschutz", document_id=doc.pk
    ).exists()


def test_upload_photoerlaubnis_goes_to_its_own_table(client, owner):
    from app.models import PhotoerlaubnisDocument
    _login(client)
    _upload(client, owner, document_type=DocumentType.PHOTOERLAUBNIS)
    assert PhotoerlaubnisDocument.objects.filter(tenant=owner).count() == 1
    assert DatenschutzDocument.objects.filter(tenant=owner).count() == 0


def test_second_upload_leaves_first(client, owner):
    _login(client)
    _upload(client, owner)
    _upload(client, owner)
    assert DatenschutzDocument.objects.filter(tenant=owner).count() == 2


def test_revoke_sets_fields(client, owner):
    _login(client)
    _upload(client, owner)
    doc = DatenschutzDocument.objects.get(tenant=owner)
    client.post(reverse("document_revoke", args=[owner.pk, "datenschutz", doc.pk]), {"revoked_note": "Widerruf"})
    doc.refresh_from_db()
    assert doc.revoked_at is not None
    assert doc.revoked_by_id == owner.pk
    assert doc.revoked_note == "Widerruf"


def test_revoke_without_note_rejected(client, owner):
    _login(client)
    _upload(client, owner)
    doc = DatenschutzDocument.objects.get(tenant=owner)
    resp = client.post(reverse("document_revoke", args=[owner.pk, "datenschutz", doc.pk]), {"revoked_note": "  "})
    assert resp.status_code == 400
    doc.refresh_from_db()
    assert doc.revoked_at is None


def test_download_returns_bytes(client, owner):
    _login(client)
    _upload(client, owner)
    doc = DatenschutzDocument.objects.get(tenant=owner)
    resp = client.get(reverse("document_download", args=[owner.pk, "datenschutz", doc.pk]))
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 x"
    # Inline viewing must stay sandboxed so a crafted PDF can't run same-origin JS.
    assert resp["Content-Security-Policy"] == "sandbox"
    assert resp["Content-Disposition"].startswith("inline")


def test_upload_mietbedingungen_per_tenant(client, owner):
    # Mietbedingungen now filed under the person, not the room assignment.
    _login(client)
    _upload(client, owner, document_type=DocumentType.MIETBEDINGUNGEN)
    doc = MietbedingungenDocument.objects.get(tenant=owner)
    assert doc.signed_at == datetime.date(2026, 8, 1)
    assert doc.uploaded_by_id == owner.pk


def test_upload_mietvertrag_two_party_signing(client, owner):
    from django.core.files.uploadedfile import SimpleUploadedFile
    _login(client)
    client.post(reverse("document_upload", args=[owner.pk]), {
        "document_type": DocumentType.MIETVERTRAG,
        "renter_signed_at": "2026-08-01",
        "company_signed_at": "2026-08-03",
        "company_signed_by": str(owner.pk),
        "document_file": SimpleUploadedFile("v.pdf", b"%PDF-1.4 v", content_type="application/pdf"),
    })
    doc = MietvertragDocument.objects.get(tenant=owner)
    assert doc.renter_signed_at == datetime.date(2026, 8, 1)
    assert doc.company_signed_at == datetime.date(2026, 8, 3)
    assert doc.company_signed_by_id == owner.pk


def test_upload_mietvertrag_requires_company_signer(client, owner):
    from django.core.files.uploadedfile import SimpleUploadedFile
    _login(client)
    resp = client.post(reverse("document_upload", args=[owner.pk]), {
        "document_type": DocumentType.MIETVERTRAG,
        "renter_signed_at": "2026-08-01",
        "company_signed_at": "2026-08-03",
        # company_signed_by omitted
        "document_file": SimpleUploadedFile("v.pdf", b"%PDF-1.4 v", content_type="application/pdf"),
    })
    assert resp.status_code == 400
    assert not MietvertragDocument.objects.filter(tenant=owner).exists()


def _sepa_data(**overrides):
    from django.core.files.uploadedfile import SimpleUploadedFile
    data = {
        "document_type": DocumentType.SEPA_LASTSCHRIFTMANDAT,
        "signed_at": "2026-08-01",
        "mandatsreferenz": "CA-2026-0001",
        "kontoinhaber": "Owner Self",
        "bank_name": "Sparkasse Heidelberg",
        "iban": "DE89370400440532013000",
        "bic": "COBADEFFXXX",
        "document_file": SimpleUploadedFile("s.pdf", b"%PDF-1.4 s", content_type="application/pdf"),
    }
    data.update(overrides)
    return data


def test_upload_sepa_stores_structured_fields(client, owner):
    from app.models import SepaLastschriftmandatDocument
    _login(client)
    client.post(reverse("document_upload", args=[owner.pk]), _sepa_data())
    doc = SepaLastschriftmandatDocument.objects.get(tenant=owner)
    assert doc.mandatsreferenz == "CA-2026-0001"
    assert doc.iban == "DE89370400440532013000"
    assert doc.bic == "COBADEFFXXX"
    assert doc.signed_at == datetime.date(2026, 8, 1)


def test_upload_sepa_requires_all_mandate_fields(client, owner):
    from app.models import SepaLastschriftmandatDocument
    _login(client)
    resp = client.post(reverse("document_upload", args=[owner.pk]), _sepa_data(iban="  "))
    assert resp.status_code == 400
    assert not SepaLastschriftmandatDocument.objects.filter(tenant=owner).exists()


def test_upload_bescheid_with_signer(client, owner):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from app.models import BescheidAusbildungsstelleDocument
    _login(client)
    client.post(reverse("document_upload", args=[owner.pk]), {
        "document_type": DocumentType.BESCHEID_AUSBILDUNGSSTELLE,
        "signed_at": "2026-08-01",
        "signed_by": str(owner.pk),
        "document_file": SimpleUploadedFile("b.pdf", b"%PDF-1.4 b", content_type="application/pdf"),
    })
    doc = BescheidAusbildungsstelleDocument.objects.get(tenant=owner)
    assert doc.signed_at == datetime.date(2026, 8, 1)
    assert doc.signed_by_id == owner.pk


def test_upload_bescheid_requires_signer(client, owner):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from app.models import BescheidAusbildungsstelleDocument
    _login(client)
    resp = client.post(reverse("document_upload", args=[owner.pk]), {
        "document_type": DocumentType.BESCHEID_AUSBILDUNGSSTELLE,
        "signed_at": "2026-08-01",
        # signed_by omitted
        "document_file": SimpleUploadedFile("b.pdf", b"%PDF-1.4 b", content_type="application/pdf"),
    })
    assert resp.status_code == 400
    assert not BescheidAusbildungsstelleDocument.objects.filter(tenant=owner).exists()


def test_upload_selbstverpflichtung(client, owner):
    from app.models import SelbstverpflichtungEngagementDocument
    _login(client)
    _upload(client, owner, document_type=DocumentType.SELBSTVERPFLICHTUNG_ENGAGEMENT)
    doc = SelbstverpflichtungEngagementDocument.objects.get(tenant=owner)
    assert doc.signed_at == datetime.date(2026, 8, 1)
    assert doc.uploaded_by_id == owner.pk


def _make_sepa(tenant):
    from app.models import SepaLastschriftmandatDocument
    return SepaLastschriftmandatDocument.objects.create(
        tenant=tenant, file_name="s.pdf", file_data=b"%PDF-1.4 s",
        signed_at=datetime.date(2026, 8, 1),
        uploaded_at=datetime.datetime(2026, 8, 2, tzinfo=datetime.timezone.utc),
        uploaded_by=tenant, mandatsreferenz="R1", kontoinhaber="Owner Self",
        bank_name="Bank", iban="DE00", bic="BICX",
    )


@pytest.fixture
def finanzierung_user(db):
    """A tenant in AG Finanzierung only — not MV, not the document's owner."""
    Tenant.objects.create(
        first_name="Fin", last_name="Anz", email="fin@example.com",
        intranet_username="fin_user", intranet_uuid="00000000-0000-0000-0000-000000000030",
    )
    User.objects.create_user(username="fin_user", password="x").groups.add(
        Group.objects.get_or_create(name="ag.finanzierung")[0]
    )
    return "fin_user"


def test_finanzierung_can_download_sepa(client, owner, finanzierung_user):
    doc = _make_sepa(owner)
    client.login(username=finanzierung_user, password="x")
    resp = client.get(reverse("document_download", args=[owner.pk, "sepa_lastschriftmandat", doc.pk]))
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 s"


def test_finanzierung_cannot_download_other_document_types(client, owner, finanzierung_user):
    doc = DatenschutzDocument.objects.create(
        tenant=owner, file_name="d.pdf", file_data=b"x", signed_at=datetime.date(2026, 8, 1),
        uploaded_at=datetime.datetime(2026, 8, 2, tzinfo=datetime.timezone.utc), uploaded_by=owner,
    )
    client.login(username=finanzierung_user, password="x")
    resp = client.get(reverse("document_download", args=[owner.pk, "datenschutz", doc.pk]))
    assert resp.status_code == 403


def test_finanzierung_cannot_upload_sepa(client, owner, finanzierung_user):
    from app.models import SepaLastschriftmandatDocument
    client.login(username=finanzierung_user, password="x")
    resp = client.post(reverse("document_upload", args=[owner.pk]), _sepa_data())
    assert resp.status_code == 403
    assert not SepaLastschriftmandatDocument.objects.filter(tenant=owner).exists()


def test_tenant_cannot_upload_own_document(client, db):
    # A plain tenant (not Mietverwaltung) may not add documents to their own record.
    t = Tenant.objects.create(
        first_name="Plain", last_name="Tenant", email="p@example.com",
        intranet_username="plain_t", intranet_uuid="00000000-0000-0000-0000-000000000099",
    )
    User.objects.create_user(username="plain_t", password="x")
    client.login(username="plain_t", password="x")
    resp = _upload(client, t)
    assert resp.status_code == 403
    assert not DatenschutzDocument.objects.filter(tenant=t).exists()
