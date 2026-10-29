import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission, User

from ai import flusso, markdown
from ai.gateway import esecuzione, finto
from ai.models import AnelloCatena, Conversazione, MessaggioChat, Modello, Profilo, Provider, Turno


@pytest.fixture
def scena(db, client, monkeypatch):
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    monkeypatch.setattr(flusso, "INTERVALLO", 0)
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto", prezzo_input=Decimal(1),
                                     prezzo_output=Decimal(1))
    for compito in ("chat", "titoli"):
        p = Profilo.objects.create(nome=compito, compito=compito)
        AnelloCatena.objects.create(profilo=p, modello=modello, ordine=1)
    utente = User.objects.create_user("anna", password="x", first_name="Anna")
    utente.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    client.force_login(User.objects.get(pk=utente.pk))
    return {"utente": utente, "conversazione": Conversazione.objects.create(utente=utente, titolo="Prova")}


def _eventi(risposta):
    testo = "".join(p.decode() if isinstance(p, bytes) else p for p in risposta.streaming_content)
    eventi = []
    for blocco in testo.strip().split("\n\n"):
        nome = next((r[7:] for r in blocco.splitlines() if r.startswith("event: ")), None)
        dati = next((r[6:] for r in blocco.splitlines() if r.startswith("data: ")), None)
        if nome:
            eventi.append((nome, json.loads(dati)))
    return eventi


def test_flusso_di_un_turno_in_corso_fino_alla_fine(client, scena):
    c = scena["conversazione"]
    turno = Turno.objects.create(conversazione=c, utente=scena["utente"], testo="Sto ",
                                 avanzamento=[{"strumento": "data_e_ora", "stato": "in corso", "passo": 1}])
    risposta = client.get(f"/ai/flusso/{turno.pk}/")
    assert risposta["Content-Type"].startswith("text/event-stream") and risposta["X-Accel-Buffering"] == "no"
    pezzi = (p.decode() for p in risposta.streaming_content)
    primo = next(pezzi) + next(pezzi)                                       # un passo: avanzamento e testo
    assert "event: avanzamento" in primo and "data_e_ora" in primo and '"delta": "Sto "' in primo
    Turno.objects.filter(pk=turno.pk).update(testo="Sto controllando", stato="completato")
    MessaggioChat.objects.create(conversazione=c, ruolo="assistente", testo="**Fatto**: sono le 10.")
    resto = "".join(pezzi)
    assert "event: fine" in resto and "<strong>Fatto</strong>" in resto


def test_ripresa_da_last_event_id(client, scena):
    turno = Turno.objects.create(conversazione=scena["conversazione"], utente=scena["utente"], testo="0123456789")
    pezzi = (p.decode() for p in client.get(f"/ai/flusso/{turno.pk}/", HTTP_LAST_EVENT_ID="6").streaming_content)
    testo = "".join(next(pezzi) for _ in range(2))
    assert '"delta": "6789"' in testo and "id: 10" in testo


def test_flusso_solo_del_proprietario(client, scena):
    altro = User.objects.create_user("bruno", password="x")
    c = Conversazione.objects.create(utente=altro)
    turno = Turno.objects.create(conversazione=c, utente=altro)
    assert client.get(f"/ai/flusso/{turno.pk}/").status_code == 404


def test_invio_dalla_pagina_e_titolo_automatico(client, scena):
    c = scena["conversazione"]
    with finto.con_copione([["Ecco gli **ordini** di oggi."], ["Ordini del giorno"]]):
        r = client.post(f"/ai/chat/{c.pk}/invia/", {"testo": "Che ordini ho oggi?"}, HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert "<strong>ordini</strong>" in html and "data-flusso" not in html      # turno sincrono: già concluso
    c.refresh_from_db()
    assert c.titolo == "Ordini del giorno" and c.titolo_generato
    titolo = Turno.objects.get(compito="titoli")
    assert titolo.stato == "completato" and titolo.costo > 0


def test_pagina_con_turno_in_corso_mostra_la_bolla(client, scena):
    c = scena["conversazione"]
    MessaggioChat.objects.create(conversazione=c, ruolo="utente", testo="Domanda")
    turno = Turno.objects.create(conversazione=c, utente=scena["utente"])
    html = client.get(f"/ai/chat/{c.pk}/").content.decode()
    assert f'data-flusso="/ai/flusso/{turno.pk}/"' in html and f"/ai/turno/{turno.pk}/stop/" in html


def test_stop(client, scena):
    turno = Turno.objects.create(conversazione=scena["conversazione"], utente=scena["utente"])
    assert client.post(f"/ai/turno/{turno.pk}/stop/").status_code == 204
    turno.refresh_from_db()
    assert turno.richiesta_stop


def test_flusso_asincrono_sotto_asgi(scena, monkeypatch):
    import asyncio

    from asgiref import sync
    # in produzione la lettura gira in un altro thread; qui nel thread del test, che ha la transazione aperta
    monkeypatch.setattr(flusso, "sync_to_async", lambda f, **kw: sync.sync_to_async(f, thread_sensitive=True))
    turno = Turno.objects.create(conversazione=scena["conversazione"], utente=scena["utente"], testo="ciao",
                                 stato="completato")
    MessaggioChat.objects.create(conversazione=scena["conversazione"], ruolo="assistente", testo="ciao")

    async def raccogli():
        return [e async for e in flusso._asincrono(turno.pk, flusso._Stato())]

    from asgiref.sync import async_to_sync
    eventi = async_to_sync(raccogli)()
    assert any("event: fine" in e for e in eventi)
    assert asyncio.iscoroutinefunction(raccogli)


def test_markdown_sicuro():
    html = markdown.rendi("**ok** <img src=x onerror=alert(1)> [x](javascript:alert(1))\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<strong>ok</strong>" in html and "&lt;img" in html and 'href="javascript' not in html
    assert "<table>" in html and "<td>1</td>" in html
    assert markdown.rendi("```\n<b>codice</b>\n```") == "<pre><code>&lt;b&gt;codice&lt;/b&gt;</code></pre>"
