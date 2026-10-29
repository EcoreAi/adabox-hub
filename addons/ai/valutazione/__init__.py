"""Valutazione dell'assistente con domande d'oro: per ogni domanda un turno vero in una conversazione interna e i
controlli attesi (strumenti usati, testo che deve o non deve comparire, esito della provenienza).

- Con il modello vero (`manage.py ai_eval`) misura la qualità e il costo su richiesta.
- Con i copioni del modello finto (`manage.py ai_eval --copioni`, e nei test) verifica il percorso degli strumenti
  sui dati veri in modo deterministico: in CI blocca le regressioni.

Formato di una domanda: {"domanda", "app"?, "strumenti"? (tutti usati), "strumenti_uno_tra"? (almeno uno),
"contiene"? , "non_contiene"? (senza distinzione tra maiuscole), "esito"? (lista di esiti ammessi), "copione"?}.
Nei testi da cercare {oggi_giorno} diventa il giorno della settimana di oggi (es. giovedì)."""
import json
import time
from contextlib import contextmanager
from pathlib import Path

from django.utils import timezone

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]

FILE = Path(__file__).parent / "domande.json"


def carica(percorso=None):
    with open(percorso or FILE, encoding="utf-8") as f:
        return json.load(f)


def _strumenti_usati(turno):
    from ..models import Evento
    usati = []
    for ev in Evento.objects.filter(turno=turno, tipo=Evento.ASSISTENTE):
        usati += [b["nome"] for b in ev.dati.get("blocchi", []) if b["tipo"] == "strumento"]
    return usati


def controlla(domanda, turno, usati):
    problemi = []
    if turno.stato != "completato":
        problemi.append(f"turno {turno.get_stato_display().lower()}: {turno.errore[:200]}")
    mancanti = [s for s in domanda.get("strumenti", []) if s not in usati]
    if mancanti:
        problemi.append(f"strumenti non usati: {', '.join(mancanti)}")
    if domanda.get("strumenti_uno_tra") and not set(domanda["strumenti_uno_tra"]) & set(usati):
        problemi.append(f"nessuno tra: {', '.join(domanda['strumenti_uno_tra'])}")
    testo = turno.testo.lower()
    problemi += [f"manca «{concreto(t).lower()}»" for t in domanda.get("contiene", [])
                 if concreto(t).lower() not in testo]
    problemi += [f"non doveva esserci «{t}»" for t in domanda.get("non_contiene", []) if t.lower() in testo]
    esito = (turno.provenienza or {}).get("esito")
    if domanda.get("esito") and esito not in domanda["esito"]:
        problemi.append(f"esito {esito}, atteso {' o '.join(domanda['esito'])}")
    return problemi


def concreto(testo):
    """I segnaposto dei testi delle domande con i valori di oggi."""
    return testo.replace("{oggi_giorno}", GIORNI[timezone.localdate().weekday()])


@contextmanager
def _modello_finto():
    """Con i copioni la catena di ogni profilo è il modello finto: mai il modello vero, mai costi."""
    from .. import catalogo
    from ..models import Modello, Provider
    provider, _ = Provider.objects.get_or_create(nome="Finto (valutazione)", defaults={
        "tipo": Provider.FINTO, "locale": True, "attivo": False})
    modello, _ = Modello.objects.get_or_create(provider=provider, id_api="finto-valutazione",
                                               defaults={"etichetta": "Finto (valutazione)", "attivo": False})
    originale = catalogo.catena
    catalogo.catena = lambda profilo, azienda=None: [(modello, "")]
    try:
        yield
    finally:
        catalogo.catena = originale


def valuta(domande, utente, azienda=None, assistente=None, copioni=False):
    """[{domanda, ok, problemi, strumenti, costo, secondi, risposta}] — una conversazione interna per domanda; le
    proposte rimaste in attesa si annullano (una valutazione non modifica mai i dati)."""
    from .. import motore, proposte
    from ..gateway import finto
    from ..models import Conversazione, Proposta
    risultati = []
    for d in domande:
        conversazione = Conversazione.objects.create(
            utente=utente, nascosta=True, assistente=assistente, titolo_generato=True,
            ambito=d.get("app") or (assistente.app if assistente else ""),
            titolo=f"Valutazione del {timezone.localtime():%d/%m/%Y %H:%M}")
        inizio = time.monotonic()
        if copioni:                                      # dal JSON i pezzi arrivano come liste: il finto vuole tuple
            copione = [[tuple(p) if isinstance(p, list) else concreto(p) for p in risposta]
                       for risposta in d.get("copione", [])]
            with finto.con_copione(copione), _modello_finto():
                turno = motore.avvia(conversazione, d["domanda"], utente, azienda, compito="valutazione", sincrono=True)
        else:
            turno = motore.avvia(conversazione, d["domanda"], utente, azienda, compito="valutazione", sincrono=True)
        turno.refresh_from_db()
        for p in conversazione.proposte.filter(stato=Proposta.IN_ATTESA):
            proposte.annulla(p)
        usati = _strumenti_usati(turno)
        problemi = controlla(d, turno, usati)
        risultati.append({"domanda": d["domanda"], "ok": not problemi, "problemi": problemi, "strumenti": usati,
                          "costo": turno.costo, "secondi": round(time.monotonic() - inizio, 1),
                          "risposta": turno.testo[:300]})
    return risultati
