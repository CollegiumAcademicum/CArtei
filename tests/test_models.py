from datetime import date, timedelta
import pytest


def abfrage_for_state(state: str):
    """Return (ends_at, grace_ends_at) such that AGAbfrage.state == state."""
    today = date.today()
    if state == "open":
        return today, today + timedelta(days=7)
    if state == "grace":
        return today - timedelta(days=1), today + timedelta(days=6)
    # closed
    return today - timedelta(days=8), today - timedelta(days=1)


@pytest.mark.django_db
def test_abfrage_state_open():
    from app.models import AGAbfrage
    ends_at, grace = abfrage_for_state("open")
    a = AGAbfrage(date=date.today(), ends_at=ends_at, grace_ends_at=grace)
    assert a.state == "open"
    assert a.can_ag_edit() is True


@pytest.mark.django_db
def test_abfrage_state_grace():
    from app.models import AGAbfrage
    ends_at, grace = abfrage_for_state("grace")
    a = AGAbfrage(date=date.today(), ends_at=ends_at, grace_ends_at=grace)
    assert a.state == "grace"
    assert a.can_ag_edit() is True


@pytest.mark.django_db
def test_abfrage_state_closed():
    from app.models import AGAbfrage
    ends_at, grace = abfrage_for_state("closed")
    a = AGAbfrage(date=date.today(), ends_at=ends_at, grace_ends_at=grace)
    assert a.state == "closed"
    assert a.can_ag_edit() is False


@pytest.mark.django_db
def test_tenant_str():
    from app.models import Tenant
    import uuid
    t = Tenant(first_name="Anna", last_name="Muster", intranet_username="amuster",
               intranet_uuid=uuid.uuid4())
    assert "Anna" in str(t)
    assert "Muster" in str(t)


@pytest.mark.django_db
def test_tenant_create_without_move_in(db):
    from app.models import Tenant
    import uuid
    t = Tenant.objects.create(
        first_name="Bob", last_name="Test", email="bob@test.de",
        intranet_username="bobtest", intranet_uuid=uuid.uuid4(),
    )
    assert t.pk is not None
    assert t.move_in is None
