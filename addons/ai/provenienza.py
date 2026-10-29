"""Provenienza di una risposta, calcolata dal codice a fine turno (non dichiarata dal modello): quali strumenti hanno
fornito i dati, quanti dati personali sono stati protetti, e quali numeri della risposta non compaiono in nessun dato
letto nel turno (guardia sui numeri: segnala, non blocca)."""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .models import Evento

# numeri non attaccati a lettere, barre o trattini (codici, link, date): 1.234,56 · 1234.5 · 42
NUMERO = re.compile(r"(?<![\w/\-.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?![\w/\-]|[.,]\d)")
DATA = re.compile(r"\b\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\b|\b\d{1,2}:\d{2}\b")
LINK = re.compile(r"\]\([^)]*\)|https?://\S+")
MAX_SEGNALATI = 5


def _valore(testo, italiano=True):
    """Decimal di un numero scritto all'italiana (1.234,56) o all'inglese (1234.56, dei dati JSON)."""
    t = testo.replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif italiano and re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def numeri(testo, italiano=True):
    testo = DATA.sub(" ", LINK.sub(" ", testo or ""))
    risultato = []
    for m in NUMERO.finditer(testo):
        v = _valore(m.group(1), italiano)
        if v is not None:
            risultato.append((m.group(1), v))
    return risultato


def _da_verificare(valore):
    """I numeri piccoli interi (conteggi, elenchi) e gli anni non si controllano."""
    if valore == valore.to_integral_value():
        return not (abs(valore) < 10 or 1900 <= valore <= 2100)
    return True


def _trovato(valore, fonti):
    for f in fonti:
        if abs(f - valore) < Decimal("0.005"):
            return True
        if valore == valore.to_integral_value() and f.quantize(Decimal(1), rounding=ROUND_HALF_UP) == valore:
            return True                                     # arrotondato all'unità
    return False


def calcola(turno, testo, protetti=0):
    eventi = list(Evento.objects.filter(turno=turno).order_by("pk"))
    strumenti, letture, fonti = [], 0, []
    for ev in eventi:
        if ev.tipo == Evento.UTENTE:
            fonti += [v for _, v in numeri(ev.dati.get("testo", ""))]
        elif ev.tipo == Evento.ASSISTENTE:
            strumenti += [b["nome"] for b in ev.dati.get("blocchi", []) if b["tipo"] == "strumento"]
        elif ev.tipo == Evento.STRUMENTO:
            for r in ev.dati.get("risultati", []):
                if not r.get("errore"):
                    letture += 1
                    fonti += [v for _, v in numeri(r["contenuto"], italiano=False)]
                    fonti += [v for _, v in numeri(r["contenuto"])]
    nella_risposta = [(t, v) for t, v in numeri(testo) if _da_verificare(v)]
    non_verificati = []
    for t, v in nella_risposta:
        if not _trovato(v, fonti) and t not in non_verificati:
            non_verificati.append(t)
    if not letture:
        esito = "senza fonti" if nella_risposta else "conversazione"
    else:
        esito = "parziale" if non_verificati else "verificato"
    return {"esito": esito, "strumenti": sorted(set(strumenti)), "letture": letture, "pii": protetti,
            "non_verificati": non_verificati[:MAX_SEGNALATI], "n_non_verificati": len(non_verificati)}
