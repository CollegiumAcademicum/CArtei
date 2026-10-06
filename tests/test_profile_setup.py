from datetime import timedelta
import uuid

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from app.middleware import IMPERSONATION_GROUP
from app.models import Building, Room, Tenant, TenantRoomAssignment, WG


def _tenant(username, room=None, moved_in=None, moved_out=None, **values):
    tenant = Tenant.objects.create(
        first_name="Ada", last_name="Muster", email="ada@example.invalid",
        intranet_username=username, intranet_uuid=uuid.uuid4(),
        **values,
    )
    if room is not None:
        TenantRoomAssignment.objects.create(
            tenant=tenant, room=room, moved_in=moved_in or timezone.localdate(),
            moved_out=moved_out,
        )
    return tenant


@pytest.fixture
def room():
    building = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=building, name="1.02")
    return Room.objects.create(wg=wg, name="1.02.1", size_sqm="12.00")


@pytest.mark.django_db
@pytest.mark.parametrize("kind,blocked", [
    ("current", True), ("future", True), ("former", False), ("unassigned", False),
])
def test_gate_applies_to_current_and_future_room_holders(room, kind, blocked):
    today = timezone.localdate()
    dates = {
        "current": (today - timedelta(days=1), None),
        "future": (today + timedelta(days=10), None),
        "former": (today - timedelta(days=10), today - timedelta(days=1)),
        "unassigned": (None, None),
    }
    moved_in, moved_out = dates[kind]
    tenant = _tenant(kind, room if moved_in else None, moved_in, moved_out)
    user = User.objects.create_user(kind, password="pw")
    client = Client()
    client.force_login(user)
    response = client.get(reverse("dashboard"))
    assert response.status_code == (302 if blocked else 200)
    if blocked:
        assert response["Location"].startswith(reverse("profile_setup"))
        response = client.post(reverse("tenant_detail", args=[tenant.pk]), {
            "section": "personal", "email": "changed@example.invalid", "phone": "123",
        })
        assert response.status_code == 302
        tenant.refresh_from_db()
        assert tenant.email == "ada@example.invalid"


@pytest.mark.django_db
def test_staff_with_room_is_gated_and_must_make_explicit_choice(room):
    tenant = _tenant("admin", room, mailbox_list_opt_in=True)
    user = User.objects.create_user("admin", password="pw")
    user.groups.add(Group.objects.create(name="admins"))
    client = Client()
    client.force_login(user)
    assert client.get(reverse("admin_portal")).status_code == 302
    response = client.get(reverse("profile_setup"))
    assert response.status_code == 200
    assert response.context["form"]["mailbox_list_opt_in"].value() is None
    assert b"Bitte best" in response.content
    assert b"Dashboard" not in response.content
    assert tenant.profile_setup_completed_at is None


@pytest.mark.django_db
def test_setup_rejects_missing_or_conflicting_answers(room):
    tenant = _tenant("resident", room)
    client = Client()
    client.force_login(User.objects.create_user("resident", password="pw"))
    url = reverse("profile_setup")
    for payload in (
        {"email": "ada@example.invalid", "phone": "123"},
        {"email": "invalid", "phone": "123", "mailbox_list_opt_in": "yes"},
        {"email": "ada@example.invalid", "mailbox_list_opt_in": "no"},
        {"email": "ada@example.invalid", "phone": "123", "no_phone_number": "on", "mailbox_list_opt_in": "no"},
    ):
        assert client.post(url, payload).status_code == 200
        tenant.refresh_from_db()
        assert tenant.profile_setup_completed_at is None


@pytest.mark.django_db
def test_no_phone_and_mailbox_no_complete_setup_then_missing_email_regates(room):
    tenant = _tenant("resident", room, mailbox_list_opt_in=True)
    client = Client()
    client.force_login(User.objects.create_user("resident", password="pw"))
    response = client.post(reverse("profile_setup"), {
        "email": "corrected@example.invalid", "no_phone_number": "on",
        "mailbox_list_opt_in": "no", "next": reverse("tenant_list"),
    })
    assert response.status_code == 302
    assert response["Location"] == reverse("tenant_list")
    tenant.refresh_from_db()
    assert tenant.profile_setup_completed_at is not None
    assert tenant.email == "corrected@example.invalid"
    assert tenant.phone is None and tenant.no_phone_number
    assert not tenant.mailbox_list_opt_in
    assert client.get(reverse("dashboard")).status_code == 200
    Tenant.objects.filter(pk=tenant.pk).update(email="")
    assert client.get(reverse("dashboard")).status_code == 302


@pytest.mark.django_db
def test_phone_and_mailbox_yes_complete_setup_and_external_next_is_ignored(room):
    tenant = _tenant("resident", room)
    client = Client()
    client.force_login(User.objects.create_user("resident", password="pw"))
    response = client.post(reverse("profile_setup"), {
        "email": "ada@example.invalid", "phone": "12345",
        "mailbox_list_opt_in": "yes", "next": "https://example.com/",
    })
    assert response["Location"] == reverse("dashboard")
    tenant.refresh_from_db()
    assert tenant.mailbox_list_opt_in and tenant.phone == "12345"
    assert not tenant.no_phone_number


@pytest.mark.django_db
def test_impersonated_resident_is_gated_but_impersonator_can_stop(room):
    target = User.objects.create_user("resident", password="pw")
    _tenant("resident", room)
    original = User.objects.create_user("super", password="pw")
    original.groups.add(Group.objects.get_or_create(name=IMPERSONATION_GROUP)[0])
    client = Client()
    client.force_login(original)
    assert client.post(reverse("impersonation_start", args=[target.pk])).status_code == 302
    assert client.get(reverse("dashboard")).status_code == 302
    assert client.get(reverse("profile_setup")).status_code == 200
    assert client.post(reverse("impersonation_stop")).status_code == 302
    assert client.get(reverse("impersonation_choose")).status_code == 200


@pytest.mark.django_db
def test_staff_overview_marks_unconfirmed_mailbox_choice_pending(room):
    tenant = _tenant("resident", room, mailbox_list_opt_in=True)
    admin = User.objects.create_user("admin", password="pw")
    admin.groups.add(Group.objects.create(name="admins"))
    client = Client()
    client.force_login(admin)
    response = client.get(reverse("tenant_list"))
    assert response.status_code == 200
    assert b"Ausstehend" in response.content
    tenant.profile_setup_completed_at = timezone.now()
    tenant.phone = "123"
    tenant.save(update_fields=["profile_setup_completed_at", "phone"])
    response = client.get(reverse("tenant_list"))
    assert b"Ausstehend" not in response.content


@pytest.mark.django_db
def test_completed_resident_cannot_clear_both_phone_choices_in_profile(room):
    tenant = _tenant(
        "resident", room, profile_setup_completed_at=timezone.now(),
        no_phone_number=True,
    )
    client = Client()
    client.force_login(User.objects.create_user("resident", password="pw"))
    url = reverse("tenant_detail", args=[tenant.pk])
    assert client.get(url).status_code == 200
    response = client.post(url, {
        "section": "personal", "email": tenant.email,
        "phone": "", "no_phone_number": "",
    })
    assert response.status_code == 200
    tenant.refresh_from_db()
    assert tenant.no_phone_number
    response = client.post(url, {
        "section": "personal", "email": tenant.email,
        "phone": "123", "no_phone_number": "on",
    })
    assert response.status_code == 200
    tenant.refresh_from_db()
    assert tenant.phone is None


@pytest.mark.django_db
def test_public_info_and_logout_remain_available_during_setup(room):
    _tenant("resident", room)
    client = Client()
    client.force_login(User.objects.create_user("resident", password="pw"))
    assert client.get(reverse("landing")).status_code == 200
    assert client.post(reverse("logout")).status_code == 302
    assert client.get(reverse("profile_setup")).status_code == 302
