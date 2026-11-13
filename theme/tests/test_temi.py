import pytest
from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from theme.models import Tema

pytestmark = pytest.mark.django_db


def _tema(nome):
    return Tema.objects.get(nome=nome)


def test_temi_di_sistema_e_classico_attivo():
    assert set(Tema.objects.filter(di_sistema=True).values_list("nome", flat=True)) == {"Adabox Classico", "Adabox Green"}
    assert list(Tema.objects.filter(attivo=True).values_list("nome", flat=True)) == ["Adabox Classico"]
    assert finders.find(_tema("Adabox Green").foglio)


def test_classico_non_aggiunge_fogli(superuser, client):
    html = client.get(reverse("core:profilo")).content.decode()
    assert "data-tema=" not in html and 'class="ui-logo-cubo"' in html


def test_attivare_green_cambia_le_pagine_e_spegne_il_classico(superuser, client):
    _tema("Adabox Green").attiva()
    assert list(Tema.objects.filter(attivo=True).values_list("nome", flat=True)) == ["Adabox Green"]
    html = client.get(reverse("core:profilo")).content.decode()
    assert "theme/temi/adabox-green.css" in html and 'content="#22394a"' in html
    assert "theme/temi/adabox-green.css" in client.get(reverse("admin:index")).content.decode()
    assert "Anteprima del tema" not in html


def test_tema_caricato_serve_css_e_logo(superuser, client):
    t = Tema.objects.create(nome="Rosso", css=":root { --ui-primary: #a00; }", logo=b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                            logo_tipo="image/svg+xml")
    t.attiva()
    html = client.get(reverse("core:profilo")).content.decode()
    assert reverse("theme:tema_css", args=[t.pk]) in html and reverse("theme:tema_logo", args=[t.pk]) in html
    r = client.get(reverse("theme:tema_css", args=[t.pk]))
    assert r["Content-Type"].startswith("text/css") and b"--ui-primary: #a00" in r.content
    r = client.get(reverse("theme:tema_logo", args=[t.pk]))
    assert r["Content-Type"] == "image/svg+xml" and "sandbox" in r["Content-Security-Policy"]


def test_anteprima_solo_per_chi_la_apre(superuser, client):
    verde = _tema("Adabox Green")
    client.get(reverse("theme:tema_anteprima", args=[verde.pk]))
    html = client.get(reverse("core:profilo")).content.decode()
    assert "adabox-green.css" in html and "Anteprima del tema" in html
    altro = User.objects.create_superuser("altro", "a@example.com", "pass12345!")
    from django.test import Client
    c2 = Client()
    c2.force_login(altro)
    assert "adabox-green.css" not in c2.get(reverse("core:profilo")).content.decode()
    client.get(reverse("theme:tema_anteprima_fine"))
    assert "adabox-green.css" not in client.get(reverse("core:profilo")).content.decode()


def test_anteprima_vietata_a_chi_non_e_staff(client):
    u = User.objects.create_user("mario", password="pass12345!")
    client.force_login(u)
    client.get(reverse("theme:tema_anteprima", args=[_tema("Adabox Green").pk]))
    assert "tema_anteprima" not in client.session


def test_admin_elenco_attiva_e_carica(superuser, client):
    r = client.get(reverse("admin:theme_tema_changelist"))
    assert r.status_code == 200 and "Adabox Green" in r.content.decode()
    verde = _tema("Adabox Green")
    assert client.get(reverse("admin:theme_tema_attiva", args=[verde.pk])).status_code == 302      # GET non attiva
    assert not Tema.objects.get(pk=verde.pk).attivo
    client.post(reverse("admin:theme_tema_attiva", args=[verde.pk]))
    assert Tema.objects.get(pk=verde.pk).attivo

    r = client.post(reverse("admin:theme_tema_add"), {
        "nome": "Mio", "descrizione": "", "colore_barra": "#112233", "css": "",
        "file_css": SimpleUploadedFile("mio.css", b":root { --ui-primary: #123456; }", content_type="text/css"),
        "file_logo": SimpleUploadedFile("logo.png", b"\x89PNG\r\n\x1a\nfinto", content_type="image/png")})
    assert r.status_code == 302, r.content.decode()[:2000]
    mio = _tema("Mio")
    assert "#123456" in mio.css and mio.logo_tipo == "image/png" and not mio.attivo

    r = client.post(reverse("admin:theme_tema_add"), {"nome": "Brutto", "colore_barra": "blu", "css": "",
                                                       "file_css": SimpleUploadedFile("x.txt", b"a")})
    assert r.status_code == 200 and not Tema.objects.filter(nome="Brutto").exists()


def test_duplica_copia_il_foglio_e_i_temi_di_sistema_non_si_cancellano(superuser, client):
    verde = _tema("Adabox Green")
    client.post(reverse("admin:theme_tema_changelist"), {"action": "duplica", "_selected_action": [verde.pk]})
    copia = _tema("Adabox Green (copia)")
    assert "--ui-header: #22394a" in copia.css and not copia.di_sistema and not copia.foglio
    r = client.post(reverse("admin:theme_tema_delete", args=[verde.pk]), {"post": "yes"})
    assert r.status_code == 403 and Tema.objects.filter(pk=verde.pk).exists()
