from django.test import override_settings
from django.urls import reverse


def test_favicon_svg_con_sigla(client):
    with override_settings(THEME={"mark": "XY"}):
        r = client.get(reverse("theme:favicon"))
    assert r.status_code == 200
    assert r["Content-Type"] == "image/svg+xml"
    assert ">XY<" in r.content.decode()


def test_favicon_ico_rimanda_allo_svg(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 301
    assert r["Location"] == reverse("theme:favicon")
