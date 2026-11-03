"""Chiedi ad Ada: l'etichetta su ogni pagina, la finestra, la domanda con il contesto della pagina, i permessi."""
import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, Permission, User

import ai
import askada
from ai.gateway import esecuzione, finto
from ai.models import AnelloCatena, Conversazione, Evento, Modello, Profilo, Provider
from askada.models import Domanda
from core.registry import manifest, modules
from core.registry.groups import crea_gruppi


@pytest.fixture
def scena(db, client, monkeypatch):
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto", prezzo_input=Decimal("1"), prezzo_output=Decimal("2"))
    profilo = Profilo.objects.create(nome="Chat", compito="chat", effort="low")
    AnelloCatena.objects.create(profilo=profilo, modello=modello, ordine=1)
    for app in (ai, askada):
        crea_gruppi(manifest.leggi(Path(app.__file__).parent))
    u = User.objects.create_user("chiara", "c@example.com", "x", first_name="Chiara")
    u.groups.add(Group.objects.get(name="AI / Utente"), Group.objects.get(name="Chiedi ad Ada / Utente"))
    u.user_permissions.add(Permission.objects.get(codename="view_attivita", content_type__app_label="todo"))
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    return u


def test_etichetta_su_ogni_pagina_e_spenta_col_modulo(scena, client, monkeypatch):
    html = client.get("/dashboard/").content.decode()
    assert 'id="ak-etichetta"' in html and "askada/askada.js" in html and 'id="ak-modale"' in html
    assert 'id="ak-etichetta"' in client.get("/todo/attivita/").content.decode()
    monkeypatch.setattr(modules, "disattivati", lambda: frozenset({"askada"}))
    assert 'id="ak-etichetta"' not in client.get("/dashboard/").content.decode()


def test_senza_permessi_niente_etichetta(scena, client):
    altro = User.objects.create_user("bruno", "b@example.com", "x")
    client.force_login(altro)
    assert 'id="ak-etichetta"' not in client.get("/dashboard/").content.decode()
    assert client.get("/askada/apri/").status_code == 403 and client.post("/askada/chiedi/", {"testo": "ciao"}).status_code == 403
    altro.groups.add(Group.objects.get(name="Chiedi ad Ada / Utente"))      # senza il permesso dell'assistente: niente
    client.force_login(User.objects.get(pk=altro.pk))
    assert client.post("/askada/chiedi/", {"testo": "ciao"}).status_code == 403
    assert 'id="ak-etichetta"' not in client.get("/dashboard/").content.decode()


def test_finestra_con_i_suggerimenti_giusti(scena, client):
    html = client.get("/askada/apri/", {"url": "/dashboard/", "titolo": "Dashboard", "grafici": "1", "kpi": "1"}).content.decode()
    for testo in ("Chiedi ad Ada", "Spiegami questa pagina", "Spiegami i grafici", "Spiegami i KPI", "Che cosa dovrei fare qui?", 'name="url" value="/dashboard/"'):
        assert testo in html
    html = client.get("/askada/apri/", {"url": "/todo/attivita/", "titolo": "Attività"}).content.decode()
    assert "Spiegami i grafici" not in html and "Spiegami i KPI" not in html


def test_la_domanda_porta_con_se_la_pagina_e_continua(scena, client):
    contesto = json.dumps({"pagina": "Dashboard", "kpi": [{"app": "To-Do", "indicatori": [{"etichetta": "da fare", "valore": "3"}]}]})
    with finto.con_copione([["Il KPI ", "dice che hai 3 cose da fare."]]) as chiamate:
        r = client.post("/askada/chiedi/", {"testo": "Spiegami i KPI", "url": "/todo/attivita/", "titolo": "Attività", "contesto": contesto,
                                            "pagina": "Attività da fare 3 Scadute 0"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200
    html = r.content.decode()
    assert "Spiegami i KPI" in html and "dice che hai 3 cose da fare" in html and 'name="conversazione"' in html and "Continua nella chat" in html
    c = Conversazione.objects.get()
    assert c.ambito == "todo" and c.titolo == "Attività · Spiegami i KPI" and c.utente == scena
    domanda = chiamate[0]["messaggi"][0]["testo"]
    assert "Chiedi ad Ada" in domanda and "/todo/attivita/" in domanda and "Dati strutturati" in domanda and '"da fare"' in domanda
    assert "Testo visibile della pagina:\nAttività da fare 3" in domanda and domanda.endswith("Spiegami i KPI")
    assert Domanda.objects.filter(utente=scena, url="/todo/attivita/", conversazione=c).count() == 1
    with finto.con_copione([["Certo."]]):
        r = client.post("/askada/chiedi/", {"testo": "E i grafici?", "url": "/todo/attivita/", "titolo": "Attività", "conversazione": c.pk,
                                            "contesto": "{non json"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and Conversazione.objects.count() == 1 and c.messaggi.count() == 4 and Domanda.objects.count() == 2
    assert "Hai già chiesto qui" in client.get("/askada/apri/", {"url": "/todo/attivita/", "titolo": "Attività"}).content.decode()


def test_domanda_vuota_e_conversazione_altrui(scena, client):
    assert client.post("/askada/chiedi/", {"testo": "  ", "url": "/x/"}).status_code == 400
    altro = User.objects.create_user("bruno", "b@example.com", "x")
    sua = Conversazione.objects.create(utente=altro, titolo="Sua")
    with finto.con_copione([["ok"]]):
        client.post("/askada/chiedi/", {"testo": "ciao", "url": "/x/", "titolo": "X", "conversazione": sua.pk})
    assert sua.messaggi.count() == 0 and Conversazione.objects.filter(utente=scena).count() == 1


def test_domande_fatte_solo_per_chi_le_puo_vedere(scena, client):
    Domanda.objects.create(utente=scena, url="/x/", titolo="X", testo="Che cos'è?")
    assert client.get("/askada/domande/").status_code == 403
    scena.groups.add(Group.objects.get(name="Chiedi ad Ada / Responsabile"))
    client.force_login(User.objects.get(pk=scena.pk))
    assert "Che cos" in client.get("/askada/domande/").content.decode()
