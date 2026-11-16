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


# ---------- «da ricordare»: ciò che uno strumento chiede di non tacere ----------
# Uno strumento può restituire {"da_ricordare": {"testo": "...", "segno": 6}}: se nella risposta finale il segno (un
# numero) non compare né in cifre né in lettere, la frase si aggiunge in coda. Esempio: l'agenda con 6 appuntamenti già
# passati e 4 da venire; il modello, a voce, diceva «hai 4 appuntamenti» tacendo i passati anche con l'istruzione.
NUMERI = ["zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci", "undici", "dodici",
          "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto", "diciannove", "venti"]
DA_RICORDARE = re.compile(r'"da_ricordare":\s*(\{[^{}]*\})')


def _richieste(contenuto):
    import json
    try:
        dati = json.loads(contenuto)
        voce = dati.get("da_ricordare") if isinstance(dati, dict) else None
    except (TypeError, ValueError):                    # risultato troncato: si cerca il pezzo
        m = DA_RICORDARE.search(contenuto or "")
        try:
            voce = json.loads(m.group(1)) if m else None
        except ValueError:
            voce = None
    return [voce] if isinstance(voce, dict) and voce.get("testo") else []


def _detto(segno, testo):
    if segno is None:
        return False
    testo = (testo or "").lower()
    parole = {str(segno)} | ({NUMERI[segno]} if isinstance(segno, int) and 0 <= segno < len(NUMERI) else set())
    return any(re.search(rf"(?<![\w]){re.escape(p)}(?![\w])", testo) for p in parole)


def da_ricordare(turno, testo):
    """Le frasi da aggiungere alla risposta: quelle chieste dagli strumenti del turno e non dette."""
    frasi = []
    for ev in Evento.objects.filter(turno=turno, tipo=Evento.STRUMENTO).order_by("pk"):
        for r in ev.dati.get("risultati", []):
            if r.get("errore"):
                continue
            for voce in _richieste(r.get("contenuto")):
                if not _detto(voce.get("segno"), testo) and voce["testo"] not in frasi and voce["testo"] not in (testo or ""):
                    frasi.append(str(voce["testo"])[:300])
    return frasi
