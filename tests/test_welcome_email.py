"""Onboarding email: a provisioned tenant gets their one-time credentials."""
import pytest

from app.emails import send_welcome_email


@pytest.mark.django_db
def test_send_welcome_email(mailoutbox, settings):
    from app.models import Tenant
    settings.DEFAULT_FROM_EMAIL = "noreply@ca-hd.de"
    settings.INTRANET_URL = "https://intranet.ca-hd.de/home"
    settings.PASSWORD_GUIDE_URL = "https://collegiumacademicum.de/internet/"
    t = Tenant.objects.create(first_name="Mara", last_name="Test", email="mara@x.de")

    send_welcome_email(t, "mara_test", "OneTime-9")

    assert len(mailoutbox) == 1
    m = mailoutbox[0]
    assert m.to == ["mara@x.de"]
    assert m.from_email == "noreply@ca-hd.de"
    assert "mara_test" in m.body and "OneTime-9" in m.body       # credentials present
    assert "https://intranet.ca-hd.de/home" in m.body           # login
    assert "https://collegiumacademicum.de/internet/" in m.body  # password/WLAN guide
    assert "Username:" in m.body and "Benutzername:" in m.body    # bilingual
