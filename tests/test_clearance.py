import datetime
import itertools

import pytest
from django.utils import timezone

from app.clearance import (
    BLACK, GREEN, RED, UNKNOWN, YELLOW, approved_doc_ids, clearance_color,
)
from app.models import (
    ClearanceAction, ConfidentialityClearanceEvent, Tenant,
    VertraulichkeitserklaerungDocument, document_readers,
)


def _expected(in_group, approved, pending):
    if in_group is None:
        return UNKNOWN
    if in_group and approved:
        return GREEN
    if in_group or approved:
        return BLACK
    return YELLOW if pending else RED


@pytest.mark.parametrize(
    "in_group,approved,pending",
    list(itertools.product([True, False, None], [True, False], [True, False])),
)
def test_clearance_color_table(in_group, approved, pending):
    assert clearance_color(in_group, approved, pending) == _expected(in_group, approved, pending)


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
