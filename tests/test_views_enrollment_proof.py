import uuid
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.utils.timezone import now as tz_now
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
        mailbox_list_opt_in=False,
        soli_miete_wunsch=0,
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


def _mv_user(username="mv_user"):
    user = User.objects.create_user(username=username)
    g, _ = Group.objects.get_or_create(name="ag.mietverwaltung")
    user.groups.add(g)
    return user


def _proof_for(tenant):
    return EnrollmentProof.objects.create(
        tenant=tenant,
        enrollment_type="STUDY",
        file_name="proof.pdf",
        file_data=b"data",
        uploaded_at=tz_now(),
        valid_until="2025-03-31",
    )


@pytest.mark.django_db
def test_verify_sets_verified_at(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    target_tenant = _tenant("target2")
    proof = _proof_for(target_tenant)
    user = _mv_user()
    _tenant("mv_user")  # Tenant row so _caller() resolves
    client = Client()
    client.force_login(user)
    resp = client.post(f"/tenants/{target_tenant.pk}/enrollment-proof/{proof.pk}/verify/")
    assert resp.status_code == 302
    proof.refresh_from_db()
    assert proof.verified_at is not None
    assert proof.needs_human_review is False


@pytest.mark.django_db
def test_verify_blocked_for_non_mv(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    t = _tenant("someone3")
    proof = _proof_for(t)
    user = User.objects.create_user(username="random3")
    _tenant("random3")  # Tenant row so _caller() resolves (still blocked by group check)
    client = Client()
    client.force_login(user)
    resp = client.post(f"/tenants/{t.pk}/enrollment-proof/{proof.pk}/verify/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_revert_clears_verification(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    t = _tenant("reverted")
    proof = _proof_for(t)
    EnrollmentProof.objects.filter(pk=proof.pk).update(
        verified_at=tz_now(), needs_human_review=True, review_reason="foo",
    )
    user = _mv_user()
    _tenant("mv_user")
    client = Client()
    client.force_login(user)
    resp = client.post(f"/tenants/{t.pk}/enrollment-proof/{proof.pk}/revert/")
    assert resp.status_code == 302
    proof.refresh_from_db()
    assert proof.verified_at is None
    assert proof.needs_human_review is False
    assert proof.review_reason is None


@pytest.mark.django_db
def test_revert_blocked_for_non_mv(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    t = _tenant("someone4")
    proof = _proof_for(t)
    user = User.objects.create_user(username="random4")
    _tenant("random4")
    client = Client()
    client.force_login(user)
    resp = client.post(f"/tenants/{t.pk}/enrollment-proof/{proof.pk}/revert/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_reject_deletes_proof(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    t = _tenant("rejected")
    proof = _proof_for(t)
    user = _mv_user()
    _tenant("mv_user")
    client = Client()
    client.force_login(user)
    resp = client.post(f"/tenants/{t.pk}/enrollment-proof/{proof.pk}/reject/")
    assert resp.status_code == 302
    assert not EnrollmentProof.objects.filter(pk=proof.pk).exists()


@pytest.mark.django_db
def test_reject_blocked_for_non_mv(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    t = _tenant("someone5")
    proof = _proof_for(t)
    user = User.objects.create_user(username="random5")
    _tenant("random5")
    client = Client()
    client.force_login(user)
    resp = client.post(f"/tenants/{t.pk}/enrollment-proof/{proof.pk}/reject/")
    assert resp.status_code == 403
    assert EnrollmentProof.objects.filter(pk=proof.pk).exists()


@pytest.mark.django_db
def test_edit_updates_metadata(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    t = _tenant("editor")
    proof = _proof_for(t)
    user = User.objects.create_user(username="editor")
    client = Client()
    client.force_login(user)
    resp = client.post(f"/tenants/{t.pk}/enrollment-proof/{proof.pk}/edit/", {
        "field_of_study": "Biologie",
        "educational_institution": "Uni Freiburg",
        "valid_until": "2026-03-31",
        "enrollment_type": "STUDY",
    })
    assert resp.status_code == 302
    proof.refresh_from_db()
    assert proof.field_of_study == "Biologie"
    assert proof.last_edited_at is not None
    assert proof.last_edited_by_id == t.pk
