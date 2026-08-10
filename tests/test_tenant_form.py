import pytest


@pytest.mark.django_db
def test_form_trims_to_allowed_fields():
    from app.forms import TenantForm
    form = TenantForm(allowed_fields={"email", "phone"})
    assert set(form.fields) == {"email", "phone"}


@pytest.mark.django_db
def test_form_rejects_bad_email():
    from app.forms import TenantForm
    from app.models import Tenant
    import uuid
    t = Tenant.objects.create(first_name="A", last_name="B", email="a@b.de",
                              intranet_username="ab", intranet_uuid=uuid.uuid4())
    form = TenantForm(data={"email": "not-an-email"}, instance=t, allowed_fields={"email"})
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.django_db
def test_form_saves_allowed_field():
    from app.forms import TenantForm
    from app.models import Tenant
    import uuid
    t = Tenant.objects.create(first_name="A", last_name="B", email="a@b.de",
                              intranet_username="cd", intranet_uuid=uuid.uuid4())
    form = TenantForm(data={"email": "new@b.de"}, instance=t, allowed_fields={"email"})
    assert form.is_valid(), form.errors
    form.save()
    t.refresh_from_db()
    assert t.email == "new@b.de"
