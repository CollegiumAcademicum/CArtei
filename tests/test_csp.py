import re

from django.urls import reverse


def test_page_sends_csp_with_matching_script_nonce(client):
    resp = client.get(reverse("landing"))
    csp = resp["Content-Security-Policy"]
    assert "script-src 'self' 'nonce-" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self' https://kc.test" in csp
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    # base.html's inline script must carry the same nonce, or the browser blocks it.
    assert f'<script nonce="{nonce}">' in resp.content.decode()


def test_nonce_differs_per_response(client):
    first = client.get(reverse("landing"))["Content-Security-Policy"]
    second = client.get(reverse("landing"))["Content-Security-Policy"]
    assert first != second
