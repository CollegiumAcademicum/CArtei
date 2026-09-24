from datetime import timedelta
import csv
from pathlib import Path
import subprocess

import pytest
from django.conf import settings as django_settings
from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone

from app.document_generation.mailbox_list import (
    MailboxListGenerationError, NoMailboxResidents, generate_mailbox_list, resident_rows,
)
from app.models import Building, Room, Tenant, TenantRoomAssignment, WG


def _tenant(name, opt_in=True):
    return Tenant.objects.create(
        first_name=name, last_name="Muster", email=f"{name}@example.invalid",
        mailbox_list_opt_in=opt_in,
    )


def _assignment(tenant, room, moved_in, moved_out=None):
    return TenantRoomAssignment.objects.create(
        tenant=tenant, room=room, moved_in=moved_in, moved_out=moved_out,
    )


@pytest.mark.django_db
def test_resident_rows_use_current_neubau_tenant_wg_pairs():
    today = timezone.localdate()
    neubau = Building.objects.create(name="Neubau")
    altbau = Building.objects.create(name="Altbau")
    nb_wg = WG.objects.create(building=neubau, name="1.02")
    ab_wg = WG.objects.create(building=altbau, name="OJ 1")
    room1 = Room.objects.create(wg=nb_wg, name="1.02.1", size_sqm="12.00")
    room2 = Room.objects.create(wg=nb_wg, name="1.02.2", size_sqm="12.00")
    ab_room = Room.objects.create(wg=ab_wg, name="1", size_sqm="12.00")
    current = _tenant("Ada")
    opt_out = _tenant("Ben", False)
    former = _tenant("Cora")
    future = _tenant("Dario")
    old_building = _tenant("Eleni")
    _assignment(current, room1, today - timedelta(days=10))
    _assignment(current, room2, today - timedelta(days=2))
    _assignment(opt_out, room1, today - timedelta(days=10))
    _assignment(former, room1, today - timedelta(days=10), today)
    _assignment(future, room1, today + timedelta(days=1))
    _assignment(old_building, ab_room, today - timedelta(days=10))

    rows = resident_rows(today)
    assert len(rows) == 2
    assert {r["id"]: (r["flatnumber"], r["opt_in"]) for r in rows} == {
        f"tenant-{current.pk}": ("1.02.2", True),
        f"tenant-{opt_out.pk}": ("1.02.1", False),
    }


@pytest.mark.django_db
def test_invalid_opted_in_room_is_reported():
    today = timezone.localdate()
    building = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=building, name="1.02")
    room = Room.objects.create(wg=wg, name="wrong", size_sqm="12.00")
    _assignment(_tenant("Ada"), room, today)
    with pytest.raises(MailboxListGenerationError):
        resident_rows(today)


@pytest.mark.django_db
def test_download_is_staff_only_and_does_not_show_form_to_residents(client, monkeypatch):
    url = reverse("briefkastenliste_download")
    assert client.get(url).status_code == 302
    ordinary = User.objects.create_user("ordinary", password="x")
    mv = User.objects.create_user("mv", password="x")
    admin = User.objects.create_user("admin", password="x")
    mv.groups.add(Group.objects.get_or_create(name=django_settings.TENANT_ROLE_GROUPS["mietverwaltung"][0])[0])
    admin.groups.add(Group.objects.get_or_create(name=django_settings.TENANT_ROLE_GROUPS["admin"][0])[0])
    monkeypatch.setattr("app.views.document.generate_mailbox_list", lambda today: b"%PDF-1.5 test")

    client.force_login(ordinary)
    assert client.get(url).status_code == 403
    assert "Formulare erstellen" not in client.get(reverse("document_list")).content.decode()

    for user in (mv, admin):
        client.force_login(user)
        page = client.get(reverse("document_list"))
        assert "Formulare erstellen" in page.content.decode()
        response = client.get(url)
        assert response.status_code == 200
        assert response.content == b"%PDF-1.5 test"
        assert response["Content-Type"] == "application/pdf"
        assert response["Cache-Control"] == "private, no-store"
        assert "attachment" in response["Content-Disposition"]


@pytest.mark.django_db
@pytest.mark.parametrize("failure", [NoMailboxResidents, MailboxListGenerationError])
def test_generator_failures_return_to_documents_with_message(client, monkeypatch, failure):
    mv = User.objects.create_user("mv", password="x")
    mv.groups.add(Group.objects.get_or_create(name=django_settings.TENANT_ROLE_GROUPS["mietverwaltung"][0])[0])
    client.force_login(mv)

    def fail(today):
        raise failure

    monkeypatch.setattr("app.views.document.generate_mailbox_list", fail)
    response = client.get(reverse("briefkastenliste_download"), follow=True)
    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == reverse("document_list")
    assert list(response.context["messages"])


@pytest.mark.django_db
@pytest.mark.parametrize("tool_fails", [False, True])
def test_script_csv_contract_and_temporary_cleanup(monkeypatch, tool_fails):
    today = timezone.localdate()
    building = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=building, name="1.02")
    room = Room.objects.create(wg=wg, name="1.02.1", size_sqm="12.00")
    tenant = _tenant("Ada")
    _assignment(tenant, room, today)
    temporary_paths = []

    def fake_run(command, **kwargs):
        workdir = Path(kwargs["cwd"])
        temporary_paths.append(workdir)
        assert command[0]
        assert command[-1] == str(workdir / "residents.csv")
        with (workdir / "residents.csv").open(newline="") as source:
            assert list(csv.DictReader(source)) == [{
                "id": f"tenant-{tenant.pk}", "forename": "Ada",
                "surename": "Muster", "flatnumber": "1.02.1",
            }]
        with (workdir / "preferences.csv").open(newline="") as source:
            assert list(csv.DictReader(source)) == [{
                "username": f"tenant-{tenant.pk}", "mailbox_name": "True",
            }]
        if tool_fails:
            raise subprocess.CalledProcessError(1, command)
        (workdir / "briefkastenliste-pdfjam.pdf").write_bytes(b"%PDF-1.5")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("app.document_generation.mailbox_list.subprocess.run", fake_run)
    if tool_fails:
        with pytest.raises(MailboxListGenerationError):
            generate_mailbox_list(today)
    else:
        assert generate_mailbox_list(today) == b"%PDF-1.5"
    assert temporary_paths and not temporary_paths[0].exists()
