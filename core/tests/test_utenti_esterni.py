"""Utenti esterni (clienti del portale) e pagine per impostare la password da un link."""
import re

from django.contrib.auth.models import User
from django.core import mail

from core.models import ProfiloUtente


def _esterno():
    u = User.objects.create_user("cliente", "cliente@example.com", "pass12345!")
    ProfiloUtente.objects.update_or_create(utente=u, defaults={"esterno": True})
    return u


def test_l_esterno_vede_solo_il_portale(client, db, settings):
    settings.PORTALE_HOME, settings.PORTALE_PERCORSI = "/portale-prova/", ["/portale-prova/"]
    client.force_login(_esterno())
    for percorso in ("/", "/dashboard/", "/app/", "/api/v1/core/aziende/", "/admin/", "/impostazioni/"):
        r = client.get(percorso)
        assert r.status_code == 302 and r["Location"] == "/portale-prova/", percorso
    assert client.get("/accounts/password_change/").status_code == 200
    assert client.get("/favicon.svg").status_code == 200


def test_senza_portale_una_pagina_che_lo_spiega(client, db, settings):
    settings.PORTALE_HOME = ""
    client.force_login(_esterno())
    r = client.get("/dashboard/")
    assert r.status_code == 403 and "Area riservata" in r.content.decode()


def test_gli_interni_non_cambiano(client, db):
    interno = User.objects.create_user("interno", password="x")
    client.force_login(interno)
    assert client.get("/dashboard/").status_code == 200


def test_password_dimenticata_fino_alla_nuova(client, db):
    _esterno()
    assert "Password dimenticata?" in client.get("/accounts/login/").content.decode()
    r = client.post("/accounts/password_reset/", {"email": "cliente@example.com"})
    assert r.status_code == 302 and len(mail.outbox) == 1
    link = re.search(r"https?://[^/]+(/accounts/reset/\S+/)", mail.outbox[0].body).group(1)
    assert "cliente" in mail.outbox[0].body
    r = client.get(link, follow=True)
    assert "Scegli la password" in r.content.decode()
    r = client.post(r.redirect_chain[-1][0], {"new_password1": "Nuova-Pass-2026", "new_password2": "Nuova-Pass-2026"},
                    follow=True)
    assert "Password salvata" in r.content.decode()
    assert User.objects.get(username="cliente").check_password("Nuova-Pass-2026")
