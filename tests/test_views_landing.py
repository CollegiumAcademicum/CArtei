from django.urls import reverse


def test_landing_public(client):
    """Landing page is reachable without login."""
    resp = client.get(reverse("landing"))
    assert resp.status_code == 200
    assert b"CArtei" in resp.content
    assert b"Roadmap" in resp.content


def test_root_redirects_anonymous_to_landing(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.url == reverse("landing")
