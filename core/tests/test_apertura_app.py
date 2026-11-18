"""Dove si apre l'app installata: scelta personale nel profilo e scorciatoie sull'icona."""
import json

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from core.models import ProfiloUtente


@pytest.fixture
def mario(db, client):
    u = User.objects.create_user("mario", "mario@example.com", "x")
    u.user_permissions.add(Permission.objects.get(codename="add_conversazione", content_type__app_label="ai"))
    client.force_login(u)
    return u


def _scegli(utente, valore):
    ProfiloUtente.objects.update_or_create(utente=utente, defaults={"apertura_app": valore})


def test_senza_scelta_si_apre_in_tasca(client, mario):
    assert client.get("/tasca/?da=app").status_code == 200


def test_scelta_parla_con_ada(client, mario):
    _scegli(mario, "parla")
    r = client.get("/tasca/?da=app")
    assert r.status_code == 302 and r["Location"] == reverse("ai:parla")
    assert client.get("/tasca/").status_code == 200                # aperta a mano: niente deviazione


def test_scorciatoie_solo_se_la_pagina_si_puo_usare(client, mario):
    r = client.get("/tasca/?apri=chat")
    assert r.status_code == 302 and r["Location"] == reverse("ai:chat")
    assert client.get("/tasca/?apri=tasca").status_code == 200
    assert client.get("/tasca/?apri=inventata").status_code == 200
    mario.user_permissions.clear()
    mario = User.objects.get(pk=mario.pk)
    client.force_login(mario)
    assert client.get("/tasca/?apri=parla").status_code == 200    # senza l'assistente resta In tasca


def test_scelta_dal_profilo(client, mario):
    r = client.post(reverse("core:apertura_app"), {"apertura_app": "chat"})
    assert r.status_code == 302 and ProfiloUtente.objects.get(utente=mario).apertura_app == "chat"
    assert "Quando apri l" in client.get(reverse("core:profilo")).content.decode()


def test_manifest_con_le_scorciatoie(client, db):
    dati = json.loads(client.get(reverse("theme:manifest")).content)
    urls = [s["url"] for s in dati["shortcuts"]]
    assert urls[:3] == ["/tasca/?apri=parla", "/tasca/?apri=chat", "/tasca/?apri=tasca"]
