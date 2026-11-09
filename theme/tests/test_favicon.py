import pytest
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


def _tema_con_template(settings, cartella, nome, contenuto):
    file = cartella / nome
    file.parent.mkdir(parents=True)
    file.write_text(contenuto)
    settings.TEMPLATES = [{**settings.TEMPLATES[0], "DIRS": [cartella, *settings.TEMPLATES[0].get("DIRS", [])]}]


def test_un_tema_sostituisce_la_favicon(client, settings, tmp_path):
    _tema_con_template(settings, tmp_path, "theme/partials/_favicon.svg", '<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>')
    assert client.get(reverse("theme:favicon")).content.decode() == '<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>'


@pytest.fixture
def statici_del_tema(settings, tmp_path):
    from django.contrib.staticfiles import finders
    settings.STATICFILES_DIRS = [tmp_path]
    finders.get_finder.cache_clear()
    yield tmp_path
    finders.get_finder.cache_clear()


def test_icone_png_dal_tema_se_ci_sono(client, statici_del_tema):
    (statici_del_tema / "theme").mkdir()
    (statici_del_tema / "theme" / "icona-180.png").write_bytes(b"\x89PNG\r\n\x1a\nDEL TEMA")
    assert client.get(reverse("theme:icona", args=[180])).content == b"\x89PNG\r\n\x1a\nDEL TEMA"
    disegnata = client.get(reverse("theme:icona", args=[192])).content      # le altre misure: il cubo di sempre
    assert disegnata.startswith(b"\x89PNG") and b"DEL TEMA" not in disegnata


def test_theme_color_dal_tema(client, settings, staff):
    assert client.get(reverse("theme:manifest")).json()["theme_color"] == "#1e3a8a"
    settings.THEME = {**settings.THEME, "theme_color": "#4e7c2e"}
    assert client.get(reverse("theme:manifest")).json()["theme_color"] == "#4e7c2e"
    assert '<meta name="theme-color" content="#4e7c2e">' in client.get(reverse("core:dashboard")).content.decode()
