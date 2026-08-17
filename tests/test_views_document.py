import datetime

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from app.models import DatenschutzDocument, DocumentSigner, DocumentType, Tenant


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
        "signer_ids": str(tenant.pk),
        "document_file": SimpleUploadedFile("d.pdf", b"%PDF-1.4 x", content_type="application/pdf"),
    }
    data.update(overrides)
    return client.post(reverse("document_upload", args=[tenant.pk]), data)


def test_upload_creates_document_and_signer(client, owner):
    _login(client)
    _upload(client, owner)
    doc = DatenschutzDocument.objects.get(tenant=owner)
    assert doc.signed_at == datetime.date(2026, 8, 1)
    assert doc.uploaded_by_id == owner.pk
    assert doc.revoked_at is None
    assert DocumentSigner.objects.filter(
        document_type="datenschutz", document_id=doc.pk, tenant=owner
    ).exists()


def test_upload_with_cosigner_records_both_signers(client, owner):
    other = Tenant.objects.create(
        first_name="Co", last_name="Signer", email="c@example.com",
        intranet_username="co_signer",
        intranet_uuid="00000000-0000-0000-0000-000000000011",
    )
    _login(client)
    _upload(client, owner, signer_ids=[str(owner.pk), str(other.pk)])
    doc = DatenschutzDocument.objects.get(tenant=owner)
    signer_ids = set(
        DocumentSigner.objects.filter(document_type="datenschutz", document_id=doc.pk)
        .values_list("tenant_id", flat=True)
    )
    assert signer_ids == {owner.pk, other.pk}


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
