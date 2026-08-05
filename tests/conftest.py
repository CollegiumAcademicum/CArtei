import pytest


@pytest.fixture(scope="session")
def django_db_setup(django_test_environment, django_db_blocker):
    """Make managed=False domain models temporarily managed so SQLite test DB creates them."""
    import django.db.models as djmodels
    from app import models as app_models

    unmanaged = [
        obj
        for name in dir(app_models)
        if isinstance((obj := getattr(app_models, name)), type)
        and issubclass(obj, djmodels.Model)
        and not obj._meta.abstract
        and not obj._meta.managed
    ]
    for m in unmanaged:
        m._meta.managed = True

    with django_db_blocker.unblock():
        from django.test.utils import setup_databases, teardown_databases
        old_config = setup_databases(verbosity=0, interactive=False)

    yield

    with django_db_blocker.unblock():
        teardown_databases(old_config, verbosity=0)

    for m in unmanaged:
        m._meta.managed = False
