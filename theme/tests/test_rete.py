"""PLT-19: rete.js è su ogni pagina dell'applicazione; i form delle viste hanno la bozza locale (per utente) e
dicono se tornano con errori; la chat di Ada gestisce da sé i propri errori."""
import pytest
from django.contrib.auth.models import User
from django.contrib.staticfiles import finders


def test_lo_script_esiste_e_gestisce_gli_errori():
    js = open(finders.find("theme/rete.js"), encoding="utf-8").read()
    for evento in ("htmx:sendError", "htmx:responseError", "htmx:timeout", "'offline'", "'online'", "data-errori-propri"):
        assert evento in js


@pytest.mark.django_db
def test_form_con_bozza_e_script_nella_pagina(client, superuser):
    html = client.get("/core/aziende/nuovo/").content.decode()
    assert "theme/rete.js" in html and f'data-bozza="{superuser.pk}"' in html and "data-con-errori" not in html
    html = client.post("/core/aziende/nuovo/", {"nome": ""}).content.decode()       # torna con errori
    assert "data-con-errori" in html


@pytest.mark.django_db
def test_chi_non_e_entrato_non_ha_bozze(client):
    User.objects.create_user("x", "x@example.com", "pass12345!")
    assert "data-bozza" not in client.get("/accounts/login/").content.decode()
