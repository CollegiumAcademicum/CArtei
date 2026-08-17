import datetime

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from app.models import DatenschutzDocument, DocumentSigner, Tenant


@pytest.fixture
def owner(db):
    t = Tenant.objects.create(
        first_name="Owner", last_name="Doc", email="od@example.com",
        intranet_username="owner_dd", intranet_uuid="00000000-0000-0000-0000-000000000020",
    )
    User.objects.create_user(username="owner_dd", password="x")
    return t


def test_detail_lists_document_with_signer(client, owner):
    doc = DatenschutzDocument.objects.create(
        tenant=owner, file_name="d.pdf",
        file_data=b"x", signed_at=datetime.date(2026, 8, 1),
        uploaded_at=datetime.datetime(2026, 8, 2, 9, 0, tzinfo=datetime.timezone.utc),
        uploaded_by=owner,
    )
    DocumentSigner.objects.create(document_type="datenschutz", document_id=doc.pk, tenant=owner)
    client.login(username="owner_dd", password="x")
    html = client.get(reverse("tenant_detail", args=[owner.pk])).content.decode()
    assert "Datenschutz" in html
    assert "Owner Doc" in html  # signer name
    assert "d.pdf" in html
