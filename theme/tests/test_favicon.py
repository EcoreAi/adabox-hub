from django.urls import reverse


def test_favicon_svg_con_il_cubo_del_logo(client):
    r = client.get(reverse("theme:favicon"))
    svg = r.content.decode()
    assert r.status_code == 200 and r["Content-Type"] == "image/svg+xml"
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"') and svg.count("<path") == 4 and "{#" not in svg


def test_favicon_ico_rimanda_allo_svg(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 301
    assert r["Location"] == reverse("theme:favicon")
