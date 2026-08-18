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


def test_assignment_field_associates_with_housing_form(client, scene):
    # The assignment cards now live OUTSIDE <form id="form-housing">, so their
    # edit fields must carry form="form-housing" to still batch-save. This is
    # what lets the document <form>s sit inside the card without nesting.
    client.login(username="mv_tda", password="x")
    resp = client.get(reverse("tenant_detail", args=[scene["tenant"].pk]))
    body = resp.content.decode()
    pk = scene["assignment"].pk
    # The room <select> for this assignment carries the form-association attr.
    assert re.search(
        rf'name="room_{pk}-room"[^>]*form="form-housing"'
        rf'|form="form-housing"[^>]*name="room_{pk}-room"',
        body,
    ), "assignment field is not associated with form-housing"
    # And the document upload form for the same assignment is present in the page.
    assert reverse("assignment_document_upload", args=[pk]) in body


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
