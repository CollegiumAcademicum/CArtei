from django.test import override_settings


@override_settings(CARTEI_VERSION="abc1234")
def test_version_endpoint_is_public_plain_text(client):
    resp = client.get("/version/")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/plain")
    assert resp.content.decode() == "abc1234"


@override_settings(CARTEI_VERSION="abc1234")
def test_version_in_footer(client):
    html = client.get("/info/").content.decode()
    assert "Version abc1234" in html
