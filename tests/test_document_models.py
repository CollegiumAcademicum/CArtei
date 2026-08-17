import datetime

import pytest

from app.models import Document, DocumentSigner, DocumentType, Tenant


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(
        first_name="Lea", last_name="Test", email="lea@example.com",
        intranet_username="ltest_docm", intranet_uuid="00000000-0000-0000-0000-000000000001",
    )


def test_document_and_signers_roundtrip(db, tenant):
    doc = Document.objects.create(
        tenant=tenant, document_type=DocumentType.DATENSCHUTZ,
        file_name="d.pdf", file_data=b"x", signed_at=datetime.date(2026, 8, 1),
        uploaded_at=datetime.datetime(2026, 8, 2, 9, 0, tzinfo=datetime.timezone.utc),
        uploaded_by=tenant,
    )
    DocumentSigner.objects.create(document=doc, tenant=tenant)
    assert doc.signers.count() == 1
    assert Document.objects.get(pk=doc.pk).document_type == "datenschutz"


def test_tenant_has_no_consent_date_fields():
    field_names = {f.name for f in Tenant._meta.get_fields()}
    assert "data_priv_signed_at" not in field_names
    assert "photo_allowance_signed_at" not in field_names
