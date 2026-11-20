def test_pages_link_self_hosted_favicon(client):
    html = client.get("/info/").content.decode()
    assert 'rel="icon" type="image/svg+xml" href="/static/app/favicon.svg"' in html
    assert 'rel="icon" type="image/png" sizes="32x32" href="/static/app/favicon-32.png"' in html
    assert 'rel="apple-touch-icon" href="/static/app/favicon-180.png"' in html
    assert '<link rel="icon" href="https://' not in html


def test_favicon_ico_is_public_redirect_to_png(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code == 301
    assert resp["Location"] == "/static/app/favicon-32.png"
