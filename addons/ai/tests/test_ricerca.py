"""Ricerca approfondita: turno lungo, rapporto come documento, fonti aggiunte dal codice e link mai visti segnalati."""
import json

import pytest
from django.urls import reverse

from ai import motore, ricerca
from ai.gateway import finto
from ai.models import Conversazione, DocumentoChat, MessaggioChat, Turno
from ai.motore import turni
from ai.strumenti import registro
from ai import protezione
from ai.strumenti import web
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)


@pytest.fixture
def web_acceso(monkeypatch, settings):
    settings.AI_TURNI_SINCRONI = True
    valori = {"ai.url_ricerca_web": "http://searxng:8080", "ai.ricerca_web": True, "ai.url_pii": ""}
    originale = web.parametri.leggi
    monkeypatch.setattr(web.parametri, "leggi", lambda chiave, azienda=None: valori[chiave] if chiave in valori else originale(chiave, azienda))
    monkeypatch.setattr(protezione, "impostazioni", lambda: ("", ()))
    return valori


@pytest.fixture
def web_finto(monkeypatch, web_acceso):  # noqa: F811
    def cerca(contesto, query):
        return {"query": query, "risultati": [{"titolo": "Guida ufficiale", "url": "https://ente.gov.it/guida", "estratto": "..."},
                                              {"titolo": "Blog", "url": "https://blog.example.com/post", "estratto": "..."}]}

    def leggi(contesto, url, pagina=1):
        return {"url": url, "titolo": "Guida ufficiale [2026]", "pagina": 1, "pagine": 1, "testo": "La scadenza è il 30 giugno."}
    monkeypatch.setattr(registro._registro["cerca_web"], "funzione", cerca)
    monkeypatch.setattr(registro._registro["leggi_pagina"], "funzione", leggi)


COPIONE = [
    [("strumento", "cerca_web", {"query": "scadenza dichiarazione"})],
    [("strumento", "leggi_pagina", {"url": "https://ente.gov.it/guida"})],
    [("strumento", "scrivi_documento", {"titolo": "Rapporto scadenze", "testo": "# Sintesi\nLa scadenza è il 30 giugno "
                                        "(https://ente.gov.it/guida). Vedi anche https://inventato.example.org/x."})],
    ["La scadenza è il 30 giugno: dettagli nel rapporto."],
]


def test_ricerca_completa_con_fonti_verificate(s, web_finto):  # noqa: F811
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    with finto.con_copione(COPIONE) as chiamate:
        turno = motore.avvia(c, "Quando scade la dichiarazione?", s["u"], s["az"], compito=ricerca.COMPITO, nota=ricerca.ISTRUZIONI)
    turno.refresh_from_db()
    assert turno.stato == Turno.COMPLETATO and turno.compito == "ricerca"
    assert "RICERCA APPROFONDITA" in json.dumps(chiamate[0]["messaggi"], ensure_ascii=False)
    d = DocumentoChat.objects.get()
    assert d.versione == 2 and d.versioni.first().autore == "ada"
    fonti = d.testo.split("## Fonti consultate")[1]
    assert "1. [Guida ufficiale (2026)](https://ente.gov.it/guida)" in fonti
    assert "Da verificare" in fonti and "inventato.example.org" in fonti and "ente.gov.it/guida," not in fonti.split("Da verificare")[1]
    assert "blog.example.com" not in fonti                                   # visto nei risultati ma non letto
    ricerca.concludi(turno)                                                   # ripetuto: niente doppioni
    d.refresh_from_db()
    assert d.testo.count("## Fonti consultate") == 1


def test_senza_pagine_lette_lo_dice(s, web_finto):  # noqa: F811
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    with finto.con_copione([[("strumento", "scrivi_documento", {"titolo": "R", "testo": "Testo"})], ["Fatto."]]):
        motore.avvia(c, "domanda", s["u"], s["az"], compito=ricerca.COMPITO)
    assert "non è stata letta nessuna pagina" in DocumentoChat.objects.get().testo


def test_budget_piu_ampio_solo_per_la_ricerca(s):
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    lunga = turni._Esecuzione(Turno(conversazione=c, utente=s["u"], compito="ricerca"))
    breve = turni._Esecuzione(Turno(conversazione=c, utente=s["u"], compito="chat"))
    assert (lunga.passi, lunga.secondi, lunga.costo) == (ricerca.PASSI, ricerca.SECONDI, ricerca.COSTO)
    assert (breve.passi, breve.secondi, breve.costo) == (turni.MAX_PASSI, turni.MAX_SECONDI, turni.MAX_COSTO)


def test_scelta_nella_chat_solo_con_il_web_acceso(s, client, monkeypatch):
    visti = {}

    def finto_avvia(conv, testo, utente, azienda, **k):
        visti.update(k)
        return Turno.objects.create(conversazione=conv, utente=utente, azienda=azienda, stato=Turno.COMPLETATO)
    monkeypatch.setattr(motore, "avvia", finto_avvia)
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    monkeypatch.setattr(ricerca, "disponibile", lambda azienda: False)
    assert b"data-ricerca" not in client.get(reverse("ai:chat")).content
    client.post(reverse("ai:invia_conversazione", args=[c.pk]), {"testo": "studia il mercato", "ricerca": "1"})
    assert visti["compito"] == "chat" and "RICERCA" not in visti["nota"]
    monkeypatch.setattr(ricerca, "disponibile", lambda azienda: True)
    assert b"data-ricerca" in client.get(reverse("ai:chat")).content
    client.post(reverse("ai:invia_conversazione", args=[c.pk]), {"testo": "studia il mercato", "ricerca": "1"})
    assert visti["compito"] == "ricerca" and "RICERCA APPROFONDITA" in visti["nota"]


def test_rigenerare_una_ricerca_resta_una_ricerca(s, web_finto):  # noqa: F811
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    with finto.con_copione([["Prima versione."]]):
        motore.avvia(c, "domanda", s["u"], s["az"], compito=ricerca.COMPITO, nota=ricerca.ISTRUZIONI)
    domanda = c.messaggi.get(ruolo=MessaggioChat.UTENTE)
    with finto.con_copione([["Seconda versione."]]) as chiamate:
        turno = motore.riparti(c, domanda, domanda.testo, s["u"], s["az"])
    assert turno.compito == "ricerca" and "RICERCA APPROFONDITA" in json.dumps(chiamate[0]["messaggi"], ensure_ascii=False)


def test_disponibile_segue_la_ricerca_sul_web(s, web_acceso):  # noqa: F811
    assert ricerca.disponibile(s["az"])
    web_acceso["ai.ricerca_web"] = False
    assert not ricerca.disponibile(s["az"])


def test_link_dei_risultati_salvati_come_json_non_sono_estranei(s):
    """Il contenuto di un risultato è JSON dentro il JSON dell'evento: le virgolette protette non entrano nel link."""
    from ai.models import Evento, VersioneDocumento
    from ai import documenti_chat
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    t = Turno.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], compito="ricerca")
    contenuto = json.dumps({"query": "q", "risultati": [{"titolo": "T", "url": "https://centro.example.it/termini-2026/", "estratto": "e"}]})
    Evento.objects.create(conversazione=c, turno=t, tipo=Evento.ASSISTENTE,
                          dati={"ruolo": "assistente", "blocchi": [{"tipo": "strumento", "id": "a", "nome": "cerca_web", "argomenti": {"query": "q"}}]})
    Evento.objects.create(conversazione=c, turno=t, tipo=Evento.STRUMENTO,
                          dati={"ruolo": "strumento", "risultati": [{"id": "a", "contenuto": contenuto, "errore": False}]})
    d = documenti_chat.crea(c, s["u"], s["az"], "R", "Vedi [qui](https://centro.example.it/termini-2026/).", turno=t)
    assert d.versioni.get().autore == VersioneDocumento.ADA
    ricerca.concludi(t)
    d.refresh_from_db()
    assert "Da verificare" not in d.testo
