"""Valutazione dell'assistente con domande d'oro: per ogni domanda un turno vero in una conversazione interna e i
controlli attesi (strumenti usati, testo che deve o non deve comparire, esito della provenienza).

- Con il modello vero (`manage.py ai_eval`) misura la qualità e il costo su richiesta.
- Con i copioni del modello finto (`manage.py ai_eval --copioni`, e nei test) verifica il percorso degli strumenti
  sui dati veri in modo deterministico: in CI blocca le regressioni.

Formato di una domanda: {"domanda", "app"?, "strumenti"? (tutti usati), "strumenti_uno_tra"? (almeno uno),
"contiene"? , "non_contiene"? (senza distinzione tra maiuscole), "esito"? (lista di esiti ammessi),
"fonte"? (testo che deve stare nel titolo di uno dei risultati di cerca_conoscenza del turno),
"citazioni_verificate"? (true: la risposta cita la conoscenza e ogni citazione è verificata), "copione"?}.
Nei testi da cercare {oggi_giorno} diventa il giorno della settimana di oggi (es. giovedì).

`valuta_ricerca` misura la sola ricerca nella conoscenza, senza modello né costi: per ogni {"domanda", "fonte"} la
posizione del primo risultato il cui titolo contiene `fonte` (`manage.py ai_eval --ricerca --file domande.json`).
Da rifare a ogni cambio di come si spezzano, si pesano o si filtrano i testi."""
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


def varianti(valore):
    """Come un numero può comparire in una risposta: intero con i punti delle migliaia e, se ha decimali, con due
    decimali alla italiana («579.831», «579.831,40»)."""
    intero = f"{int(round(valore)):,}".replace(",", ".")
    if float(valore).is_integer():
        return [intero]
    return [intero, f"{valore:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")]


def _richiesta(utente, azienda):
    from core.viste.interroga import richiesta_di
    return richiesta_di(utente, azienda)


def valori_attesi(domanda, utente=None, azienda=None):
    """I numeri che la risposta deve contenere: il valore della misura (o dei suoi gruppi), calcolato adesso."""
    from core import misure
    m = dict(domanda["misura"])
    nome = m.pop("nome")
    r = misure.calcola(nome, _richiesta(utente, azienda), **m)
    return nome, ([g["valore"] for g in r["gruppi"]][:5] if m.get("per") else [r["valore"]])


def controlla(domanda, turno, usati, utente=None, azienda=None):
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
    if domanda.get("fonte") and not any(domanda["fonte"].lower() in t.lower() for t in _titoli_trovati(turno)):
        problemi.append(f"fonte «{domanda['fonte']}» non trovata da cerca_conoscenza")
    if domanda.get("misura"):
        nome, valori = valori_attesi(domanda, utente, azienda)
        for v in valori:
            forme = varianti(v)
            if not any(f in turno.testo for f in forme):
                problemi.append(f"manca il valore {forme[0]} ({nome})")
    if domanda.get("passi_massimi") and turno.passi > domanda["passi_massimi"]:
        problemi.append(f"lenta: {turno.passi} passi (massimo {domanda['passi_massimi']})")
    if domanda.get("citazioni_verificate"):
        c = (turno.provenienza or {}).get("citazioni") or {}
        if not c.get("totale"):
            problemi.append("nessuna citazione della conoscenza nella risposta")
        elif c["verificate"] < c["totale"]:
            problemi.append(f"citazioni verificate {c['verificate']} su {c['totale']}")
    return problemi


def _titoli_trovati(turno):
    """I titoli dei risultati di cerca_conoscenza nel turno."""
    from ..models import Evento
    nomi, titoli = {}, []
    for ev in Evento.objects.filter(turno=turno, tipo__in=[Evento.ASSISTENTE, Evento.STRUMENTO]).order_by("pk"):
        if ev.tipo == Evento.ASSISTENTE:
            nomi.update({b.get("id"): b["nome"] for b in ev.dati.get("blocchi", []) if b.get("tipo") == "strumento"})
            continue
        for r in ev.dati.get("risultati", []):
            if nomi.get(r.get("id")) == "cerca_conoscenza" and not r.get("errore"):
                try:
                    titoli += [v.get("titolo", "") for v in json.loads(r.get("contenuto") or "{}").get("risultati", [])]
                except (TypeError, ValueError, AttributeError):
                    pass
    return titoli


def valuta_ricerca(domande, utente, azienda=None, limite=8):
    """[{domanda, fonte, posizione (1.. o None), titoli}] e il riepilogo {trovate, in_testa, totale, mrr}: la ricerca
    di cerca_conoscenza con i permessi di `utente`, senza modello."""
    from .. import conoscenza, strumenti
    from ..models import Conversazione
    from ..strumenti.conoscenza import _visibilita
    contesto = strumenti.Contesto(utente=utente, azienda=azienda, conversazione=Conversazione(utente=utente))
    righe = []
    for d in domande:
        trovati = conoscenza.cerca(d["domanda"], utente, azienda, d.get("fonti"), d.get("app", ""), limite, _visibilita(contesto))
        titoli = [f.titolo for f, _ in trovati]
        posizione = next((i for i, t in enumerate(titoli, start=1) if d["fonte"].lower() in t.lower()), None)
        righe.append({"domanda": d["domanda"], "fonte": d["fonte"], "posizione": posizione, "titoli": titoli[:5]})
    totale = len(righe) or 1
    riepilogo = {"totale": len(righe), "trovate": sum(r["posizione"] is not None for r in righe),
                 "in_testa": sum(r["posizione"] == 1 for r in righe),
                 "mrr": round(sum(1 / r["posizione"] for r in righe if r["posizione"]) / totale, 3)}
    return righe, riepilogo


def concreto(testo):
    """I segnaposto dei testi delle domande con i valori di oggi."""
    return testo.replace("{oggi_giorno}", GIORNI[timezone.localdate().weekday()])


@contextmanager
def solo_modello(modello):
    """Ogni profilo usa solo `modello` (ai_eval --modello): per confrontare i modelli sulle stesse domande."""
    from .. import catalogo
    originali = catalogo.catena, catalogo.automatico
    catalogo.catena = catalogo.automatico = lambda profilo, azienda=None: [(modello, "")]
    try:
        yield
    finally:
        catalogo.catena, catalogo.automatico = originali


def tempi(risultati):
    """(mediana, 90° percentile) dei secondi."""
    secondi = sorted(r["secondi"] for r in risultati)
    if not secondi:
        return 0, 0
    return secondi[len(secondi) // 2], secondi[min(len(secondi) - 1, int(len(secondi) * 0.9))]


@contextmanager
def _modello_finto():
    """Con i copioni la catena di ogni profilo è il modello finto: mai il modello vero, mai costi."""
    from .. import catalogo
    from ..models import Modello, Provider
    provider, _ = Provider.objects.get_or_create(nome="Finto (valutazione)", defaults={
        "tipo": Provider.FINTO, "locale": True, "attivo": False})
    modello, _ = Modello.objects.get_or_create(provider=provider, id_api="finto-valutazione",
                                               defaults={"etichetta": "Finto (valutazione)", "attivo": False})
    originali = catalogo.catena, catalogo.automatico          # anche Automatico: con i livelli non passa dal profilo
    catalogo.catena = catalogo.automatico = lambda profilo, azienda=None: [(modello, "")]
    try:
        yield
    finally:
        catalogo.catena, catalogo.automatico = originali


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
            valore = varianti(valori_attesi(d, utente, azienda)[1][0])[0] if d.get("misura") and not d["misura"].get("per") else ""
            copione = [[tuple(p) if isinstance(p, list) else concreto(p).replace("{valore}", valore) for p in risposta]
                       for risposta in d.get("copione", [])]
            with finto.con_copione(copione), _modello_finto():
                turno = motore.avvia(conversazione, d["domanda"], utente, azienda, compito="valutazione", sincrono=True)
        else:
            turno = motore.avvia(conversazione, d["domanda"], utente, azienda, compito="valutazione", sincrono=True)
        turno.refresh_from_db()
        for p in conversazione.proposte.filter(stato=Proposta.IN_ATTESA):
            proposte.annulla(p)
        usati = _strumenti_usati(turno)
        problemi = controlla(d, turno, usati, utente, azienda)
        risultati.append({"domanda": d["domanda"], "ok": not problemi, "problemi": problemi, "strumenti": usati,
                          "costo": turno.costo, "secondi": round(time.monotonic() - inizio, 1), "passi": turno.passi,
                          "risposta": turno.testo[:300]})
    return risultati
