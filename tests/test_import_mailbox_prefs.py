import uuid

import pytest
from django.core.management import call_command
from django.utils import timezone

from app.models import Tenant


def _tenant(username, **values):
    return Tenant.objects.create(
        first_name="Ada", last_name="Muster", email=f"{username}@example.invalid",
        intranet_username=username, intranet_uuid=uuid.uuid4(), **values,
    )


@pytest.mark.django_db
def test_import_sets_opt_in_and_keeps_cartei_answers(tmp_path):
    yes, no, blank = _tenant("ada_yes"), _tenant("bo_no", mailbox_list_opt_in=True), _tenant("cy_blank")
    answered = _tenant("di_done", profile_setup_completed_at=timezone.now())
    legacy_yes = _tenant("ed_legacy", mailbox_list_opt_in=True)
    confirmed_yes = _tenant("fa_set", mailbox_list_opt_in=True, profile_setup_completed_at=timezone.now())
    csv_file = tmp_path / "prefs.csv"
    csv_file.write_text(
        "username,mailbox_name,share_study_info,freitext,is_admin\n"
        "Ada_Yes,1,1,\"multi\nline\",0\n"
        "bo_no,0,0,,0\n"
        "cy_blank,,,,0\n"
        "di_done,1,1,,0\n"
        "ghost,1,1,,0\n",
        encoding="utf-8",
    )
    call_command("import_mailbox_prefs", str(csv_file))
    for t in (yes, no, blank, answered, legacy_yes, confirmed_yes):
        t.refresh_from_db()
    assert yes.mailbox_list_opt_in is True
    assert no.mailbox_list_opt_in is False
    assert blank.mailbox_list_opt_in is False
    assert answered.mailbox_list_opt_in is False
    assert legacy_yes.mailbox_list_opt_in is False
    assert confirmed_yes.mailbox_list_opt_in is True
