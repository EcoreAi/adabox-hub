import pytest
from django.contrib.auth.models import Group, User
from pathlib import Path

import ai
from ai.models import Conversazione
from core.registry import manifest
from core.registry.groups import crea_gruppi


@pytest.fixture
def utente(db, client):
    crea_gruppi(manifest.leggi(Path(ai.__file__).parent))
    u = User.objects.create_user("chiara", "c@example.com", "x", first_name="Chiara")
    u.groups.add(Group.objects.get(name="AI / Utente"))
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    return u


def test_pagina_vuota_a_tre_colonne(client, utente):
    html = client.get("/ai/chat/").content.decode()
    assert "Ciao Chiara" in html and 'id="ai-pannello-sinistra" hidden' in html and 'id="ai-pannello-destra" hidden' in html
    for etichetta in ("Nuova chat", "Cronologia chat", "Artifact salvati", "Documenti salvati"):
        assert etichetta in html


def test_primo_messaggio_crea_la_conversazione(client, utente):
    r = client.post("/ai/chat/invia/", {"testo": "Quanti ticket sono aperti oggi?"}, HTTP_HX_REQUEST="true")
    c = Conversazione.objects.get()
    assert r.status_code == 204 and r["HX-Redirect"] == f"/ai/chat/{c.pk}/"
    assert c.titolo == "Quanti ticket sono aperti oggi?" and c.utente == utente
    assert [m.ruolo for m in c.messaggi.all()] == ["utente", "assistente"]
    r = client.post(f"/ai/chat/{c.pk}/invia/", {"testo": "E ieri?"}, HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert "E ieri?" in html and "non è ancora collegato a un modello" in html and "<html" not in html
    assert c.messaggi.count() == 4


def test_messaggio_vuoto(client, utente):
    assert client.post("/ai/chat/invia/", {"testo": "  "}, HTTP_HX_REQUEST="true").status_code == 204
    assert not Conversazione.objects.exists()


def test_cronologia_solo_mie(client, utente):
    altro = User.objects.create_user("altro", "a@example.com", "x")
    sua = Conversazione.objects.create(utente=altro, titolo="Segreta")
    mia = Conversazione.objects.create(utente=utente, titolo="Mia")
    html = client.get(f"/ai/chat/{mia.pk}/").content.decode()
    assert "Mia" in html and "Segreta" not in html
    assert client.get(f"/ai/chat/{sua.pk}/").status_code == 404
    assert client.post(f"/ai/chat/{sua.pk}/elimina/").status_code == 404


def test_preferita_ed_elimina(client, utente):
    c = Conversazione.objects.create(utente=utente, titolo="Da ritrovare")
    client.post(f"/ai/chat/{c.pk}/preferita/")
    c.refresh_from_db()
    assert c.preferita
    assert "★ Da ritrovare" in client.get("/ai/chat/").content.decode()
    client.post(f"/ai/chat/{c.pk}/elimina/")
    assert not Conversazione.objects.exists()


def test_senza_permesso(client, db):
    client.force_login(User.objects.create_user("nessuno", "n@example.com", "x"))
    assert client.get("/ai/chat/").status_code == 403


def test_manifest_dichiara_la_home():
    assert manifest.leggi(Path(ai.__file__).parent).home == "ai:chat"
