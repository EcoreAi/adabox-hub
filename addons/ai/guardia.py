"""Guardia «dati senza fonti» per le risposte a voce, prima che vengano lette.

A voce l'utente non vede fonti né avvisi: una risposta con dati inventati (appuntamenti, importi, numeri) suonerebbe
vera. Se la risposta finale contiene cifre e nel turno non è stato letto nessun dato del gestionale, il motore chiede
al modello una volta di rifarla usando gli strumenti (o di dire che non lo sa); se anche la seconda è senza fonti, alla
risposta si aggiunge un avviso, che la voce legge.

Le cifre che stanno già nella domanda, nel contesto (data, ora, giorni) o nei risultati degli strumenti non contano.
La regola è del codice, non del modello: costa solo nel caso sbagliato. La pagina vocale aspetta a parlare finché non
sa se la risposta è appoggiata a dati (vedi parla.js), così una risposta scartata non viene letta."""
import re

from .models import Evento
from .provenienza import LINK, NON_FONTI

CIFRE = re.compile(r"\d+(?:[.,:]\d+)*")
MAX_ESEMPI = 5
RICHIAMO = ("Controllo automatico: la tua risposta contiene dati precisi ({esempi}) ma in questo turno non hai letto "
            "nessun dato con gli strumenti. Se sono dati dell'azienda (appuntamenti, importi, clienti, scadenze...) "
            "leggili con gli strumenti; se non puoi, di' chiaramente che non lo sai. Non scusarti e non citare questo "
            "controllo: rispondi di nuovo all'utente, breve, per la voce.")
AVVISO = "\n\nAttenzione: non ho trovato questi dati negli strumenti, verificali prima di usarli."


def strumenti_di_dati(turno):
    """Gli strumenti del turno che hanno letto dati (non quelli che orientano o preparano scritture)."""
    usati = []
    for ev in Evento.objects.filter(turno=turno, tipo=Evento.ASSISTENTE):
        usati += [b["nome"] for b in ev.dati.get("blocchi", []) if b.get("tipo") == "strumento"]
    return [n for n in usati if n not in NON_FONTI]


def sospetti(turno, testo):
    """Le cifre della risposta che non vengono da nessuna parte: [] se il turno ha letto dati o se non ce ne sono."""
    if strumenti_di_dati(turno):
        return []
    noti = set()
    for ev in Evento.objects.filter(turno=turno, tipo__in=[Evento.UTENTE, Evento.STRUMENTO]):
        if ev.dati.get("richiamo"):
            continue                                  # il richiamo stesso contiene le cifre sospette
        if ev.tipo == Evento.UTENTE:
            noti.update(CIFRE.findall(ev.dati.get("testo", "")))
        else:
            for r in ev.dati.get("risultati", []):
                noti.update(CIFRE.findall(str(r.get("contenuto", ""))))
    trovati = []
    for cifra in CIFRE.findall(LINK.sub(" ", testo or "")):
        if cifra not in noti and cifra not in trovati:
            trovati.append(cifra)
    return trovati[:MAX_ESEMPI]


def richiama(conversazione, turno, cifre):
    """Il richiamo al modello: va nella storia del modello (non tra i messaggi della chat)."""
    Evento.objects.create(conversazione=conversazione, turno=turno, tipo=Evento.UTENTE, dati={
        "ruolo": "utente", "testo": RICHIAMO.format(esempi=", ".join(cifre)), "richiamo": True})
