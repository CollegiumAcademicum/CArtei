import datetime

import pytest
from django.contrib.auth.models import Group, User
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


def test_detail_shows_missing_type_when_no_active_doc(client, owner):
    # Owner has a Datenschutz doc but no Fotoerlaubnis -> Fotoerlaubnis is missing.
    doc = DatenschutzDocument.objects.create(
        tenant=owner, file_name="d.pdf", file_data=b"x",
        signed_at=datetime.date(2026, 8, 1),
        uploaded_at=datetime.datetime(2026, 8, 2, 9, 0, tzinfo=datetime.timezone.utc),
        uploaded_by=owner,
    )
    DocumentSigner.objects.create(document_type="datenschutz", document_id=doc.pk, tenant=owner)
    client.login(username="owner_dd", password="x")
    resp = client.get(reverse("tenant_detail", args=[owner.pk]))
    groups = {g["type"]: g for g in resp.context["document_groups"]}
    assert groups["datenschutz"]["has_active"] is True
    assert groups["photoerlaubnis"]["has_active"] is False
    assert "Noch nicht unterschrieben" in resp.content.decode()


def test_detail_offers_any_tenant_as_cosigner(client, owner):
    # The co-signer picker is a Mietverwaltung-only management control.
    User.objects.get(username="owner_dd").groups.add(
        Group.objects.get_or_create(name="ag.mietverwaltung")[0]
    )
    other = Tenant.objects.create(
        first_name="Cosign", last_name="Er", email="cs@example.com",
        intranet_username="cosign_er",
        intranet_uuid="00000000-0000-0000-0000-000000000021",
    )
    client.login(username="owner_dd", password="x")
    resp = client.get(reverse("tenant_detail", args=[owner.pk]))
    candidate_ids = {t.pk for t in resp.context["cosigner_candidates"]}
    assert other.pk in candidate_ids
    assert owner.pk not in candidate_ids  # subject is not offered as a co-signer
    assert "Cosign Er" in resp.content.decode()
