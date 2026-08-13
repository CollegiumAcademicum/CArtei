import uuid
import pytest
from django.contrib.auth.models import User
from django.test import Client
from app.models import EnrollmentProof, Tenant


def _tenant(username="uploader"):
    return Tenant.objects.create(
        intranet_username=username,
        intranet_uuid=uuid.uuid4(),
        first_name="Test",
        last_name="User",
        email="t@example.com",
        is_flinta=False,
        barrier_free_needed=False,
        mailbox_key=False,
        mailbox_list_opt_in=False,
        soli_miete_wunsch=0,
        is_sublet=False,
    )


@pytest.mark.django_db
def test_upload_requires_login():
    t = _tenant()
    client = Client()
    resp = client.post(f"/tenants/{t.pk}/enrollment-proof/upload/", {})
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


@pytest.mark.django_db
def test_upload_creates_proof(tmp_path):
    t = _tenant()
    user = User.objects.create_user(username="uploader")
    client = Client()
    client.force_login(user)

    from django.core.files.uploadedfile import SimpleUploadedFile
    pdf = SimpleUploadedFile("immatrikulation.pdf", b"%PDF-1.4 content", content_type="application/pdf")

    resp = client.post(f"/tenants/{t.pk}/enrollment-proof/upload/", {
        "enrollment_type": "STUDY",
        "field_of_study": "Informatik",
        "educational_institution": "Uni Heidelberg",
        "valid_until": "2025-03-31",
        "proof_file": pdf,
    })
    assert resp.status_code == 302
    proof = EnrollmentProof.objects.get(tenant=t)
    assert proof.field_of_study == "Informatik"
    assert proof.uploaded_by == t
    assert proof.file_name == "immatrikulation.pdf"
    assert proof.verified_at is None
    assert proof.needs_human_review is False


@pytest.mark.django_db
def test_upload_rejected_if_uploader_not_a_tenant():
    t = _tenant("target")
    user = User.objects.create_user(username="nobody")  # no matching Tenant row
    client = Client()
    client.force_login(user)

    from django.core.files.uploadedfile import SimpleUploadedFile
    pdf = SimpleUploadedFile("proof.pdf", b"data", content_type="application/pdf")
    resp = client.post(f"/tenants/{t.pk}/enrollment-proof/upload/", {
        "enrollment_type": "STUDY",
        "valid_until": "2025-03-31",
        "proof_file": pdf,
    })
    assert resp.status_code == 403
