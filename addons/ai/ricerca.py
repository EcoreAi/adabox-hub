"""Ricerca approfondita: un turno più lungo in cui Ada pianifica, cerca sul web più volte, legge le pagine, usa se
serve i dati del gestionale e consegna un rapporto come documento accanto alla chat.

Le fonti non le dichiara il modello: a fine turno il codice aggiunge al rapporto l'elenco delle pagine lette davvero
e segnala i link del testo che non sono mai comparsi nei risultati. Valgono tutte le regole della ricerca sul web
(niente dati personali nelle query, si aprono solo indirizzi già comparsi)."""
import json
import re
from decimal import Decimal

from .models import DocumentoChat, Evento, VersioneDocumento

COMPITO = "ricerca"
PASSI = 40
SECONDI = 900
COSTO = Decimal("2.00")                                 # dollari per una ricerca
MASSIME_FONTI = 40
URL = re.compile(r"https?://[^\s)\]>\"'<\\]+")

ISTRUZIONI = """L'utente ha chiesto una RICERCA APPROFONDITA. Hai più tempo e più passi di una risposta normale.
1. Dividi la domanda in 3-6 sotto-domande e cercale con cerca_web, con query diverse e precise (anche in inglese se serve).
2. Apri con leggi_pagina le fonti migliori (almeno 4 se esistono), preferendo fonti ufficiali e primarie; confronta fonti diverse e segnala i disaccordi.
3. Se servono, usa anche i dati del gestionale con gli altri strumenti.
4. Alla fine scrivi il rapporto con scrivi_documento: sintesi iniziale, sezioni per tema, conclusioni o raccomandazioni, limiti della ricerca. Cita le fonti nel testo con il loro link, solo link che hai visto nei risultati. L'elenco delle fonti lette lo aggiunge il sistema: non scriverlo tu.
5. In chat, dopo il documento, solo 3-5 righe con le conclusioni principali."""


def disponibile(azienda):
    from .strumenti import web
    return bool(web.url_servizio()) and web.abilitata(azienda)


def _chiamate(turno):
    """[(nome, argomenti, risultato)] degli strumenti riusciti nel turno."""
    nomi, uscita = {}, []
    for ev in Evento.objects.filter(turno=turno, tipo__in=[Evento.ASSISTENTE, Evento.STRUMENTO]).order_by("pk"):
        if ev.tipo == Evento.ASSISTENTE:
            nomi.update({b.get("id"): (b["nome"], b.get("argomenti") or {}) for b in ev.dati.get("blocchi", []) if b.get("tipo") == "strumento"})
        else:
            for r in ev.dati.get("risultati", []):
                if not r.get("errore") and r.get("id") in nomi:
                    uscita.append((*nomi[r["id"]], r.get("contenuto", "")))
    return uscita


def fonti(turno):
    """(pagine lette [(url, titolo)], tutti gli indirizzi comparsi nella conversazione fino a questo turno)."""
    lette, viste = [], set()
    for nome, argomenti, contenuto in _chiamate(turno):
        if nome == "leggi_pagina":
            try:
                dati = json.loads(contenuto)
            except (TypeError, ValueError):
                dati = {}
            url = dati.get("url") or argomenti.get("url", "")
            if url and url not in [u for u, _ in lette]:
                lette.append((url, dati.get("titolo") or url))
            viste.add(argomenti.get("url", ""))
    for ev in turno.conversazione.eventi.filter(tipo__in=[Evento.UTENTE, Evento.STRUMENTO], pk__lte=_ultimo_evento(turno)):
        testi = [ev.dati.get("testo", "")] if ev.tipo == Evento.UTENTE else [r.get("contenuto", "") for r in ev.dati.get("risultati", [])]
        for testo in testi:                              # il testo vero, non il JSON con le virgolette protette
            viste.update(URL.findall(_testo_di(testo)))
    viste.update(u for u, _ in lette)
    return lette[:MASSIME_FONTI], {_pulito(u) for u in viste if u}


def _testo_di(contenuto):
    """Il contenuto di un risultato: JSON (i valori, senza caratteri di escape) o testo semplice."""
    if not isinstance(contenuto, str):
        contenuto = json.dumps(contenuto, ensure_ascii=False)
    try:
        dati = json.loads(contenuto)
    except ValueError:
        return contenuto
    valori = []

    def raccogli(x):
        if isinstance(x, dict):
            for v in x.values():
                raccogli(v)
        elif isinstance(x, list):
            for v in x:
                raccogli(v)
        elif isinstance(x, str):
            valori.append(x)
    raccogli(dati)
    return "\n".join(valori)


def _ultimo_evento(turno):
    return Evento.objects.filter(turno=turno).order_by("-pk").values_list("pk", flat=True).first() or 0


def _pulito(url):
    return url.rstrip(".,;:").rstrip("/")


def concludi(turno):
    """Aggiunge ai rapporti del turno le fonti lette e l'avviso sui link mai comparsi. Nuova versione di Ada."""
    from . import documenti_chat
    documenti = DocumentoChat.objects.filter(versioni__turno=turno).distinct()
    if not documenti:
        return
    lette, viste = fonti(turno)
    for d in documenti:
        estranei = sorted({u for u in URL.findall(d.testo) if _pulito(u) not in viste})
        coda = ["", "---", "## Fonti consultate",
                "_Elenco preparato dal sistema: le pagine aperte e lette durante la ricerca._" if lette else
                "_Durante la ricerca non è stata letta nessuna pagina web: il rapporto si basa sugli estratti dei risultati e sui dati del gestionale._"]
        coda += [f"{i}. [{titolo.replace('[', '(').replace(']', ')')}]({url})" for i, (url, titolo) in enumerate(lette, 1)]
        if estranei:
            coda += ["", "> **Da verificare:** questi link del testo non sono comparsi nei risultati della ricerca: "
                     + ", ".join(estranei[:10])]
        testo = d.testo.split("\n---\n## Fonti consultate")[0].rstrip()
        documenti_chat.nuova_versione(d, testo + "\n" + "\n".join(coda) + "\n", VersioneDocumento.ADA, turno=turno)
