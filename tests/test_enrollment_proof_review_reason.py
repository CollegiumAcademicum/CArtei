import datetime
import uuid
import pytest
from app.models import EnrollmentProof, Tenant


@pytest.mark.django_db
def test_review_reason_field_round_trips():
    t = Tenant.objects.create(
        first_name="Max", last_name="Mustermann",
        email="p@x.de", intranet_username="mmustermann",
        intranet_uuid=uuid.uuid4(),
    )
    p = EnrollmentProof.objects.create(
        tenant=t, enrollment_type="STUDY", file_name="i.pdf", file_data=b"%PDF",
        uploaded_at=datetime.datetime(2026, 8, 15, tzinfo=datetime.timezone.utc),
        valid_until=datetime.date(2026, 9, 30),
        needs_human_review=True, review_reason="Signatur ungültig",
    )
    p.refresh_from_db()
    assert p.review_reason == "Signatur ungültig"
