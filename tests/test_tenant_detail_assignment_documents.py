import datetime
import re

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from app.models import (
    Building, MietbedingungenDocument, Room, Tenant, TenantRoomAssignment, WG,
)


@pytest.fixture
def scene(db):
    mv = Tenant.objects.create(
        first_name="MV", last_name="V", email="mv2@example.com",
        intranet_username="mv_tda", intranet_uuid="00000000-0000-0000-0000-000000000301",
    )
    mu = User.objects.create_user(username="mv_tda", password="x")
    mu.groups.add(Group.objects.get_or_create(name="ag.mietverwaltung")[0])
    tenant = Tenant.objects.create(
        first_name="Te", last_name="A", email="te2@example.com",
        intranet_username="te_tda", intranet_uuid="00000000-0000-0000-0000-000000000302",
    )
    b = Building.objects.create(name="NB_TDA")
    w = WG.objects.create(building=b, name="5.03")
    r = Room.objects.create(wg=w, name="5.03.1", size_sqm="11.00")
    a = TenantRoomAssignment.objects.create(
        tenant=tenant, room=r, moved_in=datetime.date(2024, 9, 1)
    )
    return {"tenant": tenant, "assignment": a}


def test_mv_sees_upload_form_for_each_type(client, scene):
    client.login(username="mv_tda", password="x")
    resp = client.get(reverse("tenant_detail", args=[scene["tenant"].pk]))
    body = resp.content.decode()
    assert 'value="mietvertrag"' in body
    assert 'value="mietbedingungen"' in body
    assert 'value="wohnungsgeberbescheinigung"' in body
    assert reverse("assignment_document_upload", args=[scene["assignment"].pk]) in body


def test_assignment_field_associates_with_per_assignment_form(client, scene):
    # Each card has its own hidden <form id="form-room-{pk}"> for per-assignment
    # save/revert. The edit fields carry form="form-room-{pk}" so they submit with
    # that form instead of wrapping (and thus nesting) the document <form>s.
    client.login(username="mv_tda", password="x")
    resp = client.get(reverse("tenant_detail", args=[scene["tenant"].pk]))
    body = resp.content.decode()
    pk = scene["assignment"].pk
    assert f'id="form-room-{pk}"' in body
    # The room <select> for this assignment carries the form-association attr.
    assert re.search(
        rf'name="room_{pk}-room"[^>]*form="form-room-{pk}"'
        rf'|form="form-room-{pk}"[^>]*name="room_{pk}-room"',
        body,
    ), "assignment field is not associated with its per-assignment form"
    # And the document upload form for the same assignment is present in the page.
    assert reverse("assignment_document_upload", args=[pk]) in body
    # The partial's template comment must not leak into the rendered page
    # (multi-line {# #} comments render as literal text in Django).
    assert "mode (" not in body
    assert "Needs: assignment" not in body


def test_existing_document_shows_download_link(client, scene):
    from django.utils.timezone import now
    MietbedingungenDocument.objects.create(
        assignment=scene["assignment"], file_name="m.pdf", file_data=b"x",
        uploaded_at=now(), uploaded_by=scene["tenant"],
        signed_at=datetime.date(2026, 8, 1),
    )
    client.login(username="mv_tda", password="x")
    resp = client.get(reverse("tenant_detail", args=[scene["tenant"].pk]))
    doc = MietbedingungenDocument.objects.get()
    assert reverse("assignment_document_download",
                   args=[scene["assignment"].pk, "mietbedingungen", doc.pk]) in resp.content.decode()
