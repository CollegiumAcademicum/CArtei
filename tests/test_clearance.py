import datetime
import itertools

import pytest
from django.utils import timezone

from app.clearance import (
    BLACK, GREEN, RED, UNKNOWN, YELLOW, approved_doc_ids, clearance_color, confirm_name_for,
)
from app.models import (
    ClearanceAction, ConfidentialityClearanceEvent, Tenant,
    VertraulichkeitserklaerungDocument, document_readers,
)


_TABLE = [
    *[((True, True, p), GREEN) for p in (True, False)],
    *[((True, False, p), BLACK) for p in (True, False)],
    *[((False, True, p), BLACK) for p in (True, False)],
    ((False, False, True), YELLOW),
    ((False, False, False), RED),
    *[((None, a, p), UNKNOWN) for a in (True, False) for p in (True, False)],
]


@pytest.mark.parametrize("args,colour", _TABLE)
def test_clearance_color_table(args, colour):
    assert clearance_color(*args) == colour


def test_clearance_color_table_is_exhaustive():
    assert {a for a, _ in _TABLE} == set(itertools.product([True, False, None], [True, False], [True, False]))


def test_confirm_name_strips_each_part():
    t = Tenant(first_name="  Max ", last_name=" Muster  ")
    assert confirm_name_for(t) == "Max Muster"
    assert confirm_name_for(Tenant(first_name="Solo ", last_name="")) == "Solo"


@pytest.mark.django_db
def test_approved_doc_ids():
    t = Tenant.objects.create(first_name="A", last_name="B", email="a@b.de")
    now = timezone.now()

    def doc():
        return VertraulichkeitserklaerungDocument.objects.create(
            tenant=t, file_name="x.pdf", file_data=b"x", uploaded_at=now,
            uploaded_by=t, signed_at=datetime.date.today(),
        )

    granted, plain, revoked = doc(), doc(), doc()
    for d, action in ((granted, ClearanceAction.GRANT), (revoked, ClearanceAction.REVOKE)):
        ConfidentialityClearanceEvent.objects.create(
            tenant=t, document=d, action=action, actor=t, created_at=now,
        )
    ids = [granted.pk, plain.pk, revoked.pk]
    assert approved_doc_ids(ids) == {granted.pk}


def test_granter_reads_only_ve():
    assert "granter" in document_readers("vertraulichkeitserklaerung")
    assert "granter" not in document_readers("datenschutz")
