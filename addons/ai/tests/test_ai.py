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
    assert "Ciao, Chiara" in html and 'id="ai-pannello-sinistra" hidden' in html and 'id="ai-pannello-destra" hidden' in html
    for etichetta in ("Nuova chat", "Cronologia chat", "Artifact salvati", "Documenti salvati"):
        assert etichetta in html
    assert html.count('class="ui-header"') == 1 and 'id="profile-menu"' in html  # header del tema, come nelle app
    assert 'ai-menu-app' not in html and 'ai-menu-utente' not in html                 # niente doppioni nella chat
    assert "data-sugg" in html and "ai-suggerimenti-app" in html


def test_app_per_limitare_la_chat(client, utente, monkeypatch):
    # app finta: il modulo ai non dipende da nessuna app, il test non deve presupporne una installata
    from ai import pagine
    finta = [{"slug": "todo", "label": "To-Do", "icon": "todo/icon.svg", "url": "/todo/attivita/"}]
    monkeypatch.setattr(pagine, "app_selezionabili", lambda user: finta)
    html = client.get("/ai/chat/").content.decode()
    assert 'data-ambito-app="todo"' in html and 'data-ambito-app="ai"' not in html
    client.post("/ai/chat/invia/", {"testo": "Cosa scade oggi?", "ambito": "todo"})
    client.post("/ai/chat/invia/", {"testo": "E nel CRM?", "ambito": "crm"})       # app non visibile: ignorata
    ambiti = dict(Conversazione.objects.values_list("titolo", "ambito"))
    assert ambiti == {"Cosa scade oggi?": "todo", "E nel CRM?": ""}
    c = Conversazione.objects.get(ambito="todo")
    html = client.get(f"/ai/chat/{c.pk}/").content.decode()
    assert "To-Do" in html and 'data-apri-app' in html and 'name="ambito" value="todo"' in html     # bottone «App»
    assert 'data-interruttore-ambiti' not in html                       # le icone sotto il campo: solo chat nuova
    client.post(f"/ai/chat/{c.pk}/invia/", {"testo": "E il CRM?", "ambito": "crm"})     # non visibile: tutte
    c.refresh_from_db()
    assert c.ambito == ""
    client.post(f"/ai/chat/{c.pk}/invia/", {"testo": "Torna alle attività", "ambito": "todo"})
    client.post(f"/ai/chat/{c.pk}/invia/", {"testo": "Senza campo ambito"})             # resta com'è
    c.refresh_from_db()
    assert c.ambito == "todo"


def test_bottone_app_e_icone_che_si_nascondono(client, utente, monkeypatch):
    from ai import pagine
    finta = [{"slug": "todo", "label": "To-Do", "icon": "todo/icon.svg", "url": "/todo/attivita/"}]
    monkeypatch.setattr(pagine, "app_selezionabili", lambda user: finta)
    html = client.get("/ai/chat/").content.decode()
    assert 'aria-controls="ai-scheda-app"' in html and 'id="ai-scheda-app"' in html and "Tutte le app" in html
    assert 'data-interruttore-ambiti' in html and 'aria-controls="ai-ambiti-griglia"' in html
    assert html.count('data-ambito-app="todo"') == 2                   # nella scheda e tra le icone


def test_primo_messaggio_crea_la_conversazione(client, utente):
    r = client.post("/ai/chat/invia/", {"testo": "Quanti ticket sono aperti oggi?"}, HTTP_HX_REQUEST="true")
    c = Conversazione.objects.get()
    assert r.status_code == 204 and r["HX-Redirect"] == f"/ai/chat/{c.pk}/"
    assert c.titolo == "Quanti ticket sono aperti oggi?" and c.utente == utente
    assert [m.ruolo for m in c.messaggi.all()] == ["utente", "assistente"]
    r = client.post(f"/ai/chat/{c.pk}/invia/", {"testo": "E ieri?"}, HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert "E ieri?" in html and "configura l&#x27;assistente" in html and "<html" not in html
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


def test_impostazioni_raggiungibili_dalla_chat(client, utente):
    assert "Impostazioni dell" not in client.get("/ai/chat/").content.decode()       # utente normale: no
    from django.contrib.auth.models import Permission
    utente.user_permissions.add(Permission.objects.get(codename="change_provider"))
    from django.contrib.auth.models import User
    client.force_login(User.objects.get(pk=utente.pk))
    assert 'href="/ai/provider/"' in client.get("/ai/chat/").content.decode()
