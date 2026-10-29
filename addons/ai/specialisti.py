"""Specialisti locali di adabox come strumenti dell'assistente: previsioni (Timestral, quantili) e decisore (protocollo
di Jev sopra EmbeddingGemma). Servizi sulla rete interna, URL nelle impostazioni, spenti se l'URL è vuoto.

Il modello sceglie cosa prevedere (vista, data, misura); la serie storica la costruisce il codice nel database con i
permessi dell'utente, i numeri li calcola il servizio: nessun numero della previsione viene dal modello linguistico.
"""
import datetime
import json
import logging
import urllib.error
import urllib.request

from django.db import models
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from .strumenti import ErroreStrumento

log = logging.getLogger("ai.specialisti")

TIMEOUT = 120
UNITA = {"mese": TruncMonth, "settimana": TruncWeek, "giorno": TruncDay}
MIN_PERIODI = 6
MAX_PERIODI = 120
MAX_ORIZZONTE = 24
QUANTILI = [0.1, 0.5, 0.9]
MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def url(chiave):
    """L'URL di un servizio dalle impostazioni ("" se non c'è o se l'impostazione non esiste)."""
    from core import parametri
    try:
        return (parametri.leggi(f"ai.{chiave}") or "").strip().rstrip("/")
    except KeyError:
        return ""


def chiama(chiave, percorso, dati, nome):
    base = url(chiave)
    if not base:
        raise ErroreStrumento(f"Il servizio di {nome} non è configurato.")
    richiesta = urllib.request.Request(f"{base}{percorso}", data=json.dumps(dati).encode(),
                                       headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
            return json.load(risposta)
    except urllib.error.HTTPError as e:
        dettaglio = e.read().decode(errors="replace")[:300]
        raise ErroreStrumento(f"Il servizio di {nome} ha rifiutato la richiesta: {dettaglio}")
    except Exception as e:
        log.warning("servizio di %s non raggiungibile: %s", nome, e)
        raise ErroreStrumento(f"Il servizio di {nome} non risponde: riprova tra poco.")


# ---------- periodi ----------

def inizio(data, per):
    if per == "mese":
        return data.replace(day=1)
    if per == "settimana":
        return data - datetime.timedelta(days=data.weekday())
    return data


def avanti(data, per, passi=1):
    if per == "mese":
        mese = data.month - 1 + passi
        return data.replace(year=data.year + mese // 12, month=mese % 12 + 1, day=1)
    return data + datetime.timedelta(days=passi * (7 if per == "settimana" else 1))


def etichetta(data, per):
    if per == "mese":
        return f"{MESI[data.month - 1]} {data.year}"
    if per == "settimana":
        return f"sett. {data:%d/%m}"
    return f"{data:%d/%m/%Y}"


def _come_data(valore):
    if isinstance(valore, datetime.datetime):
        return timezone.localtime(valore).date() if timezone.is_aware(valore) else valore.date()
    return valore


def serie_storica(vista, request, data, misura="count", per="mese", filtri=None, testo=""):
    """([(periodo, valore)] dei periodi completi fino a quello in corso escluso, periodo in corso)."""
    from .strumenti import viste
    if per not in UNITA:
        raise ErroreStrumento("«per» è mese, settimana o giorno.")
    espressione, _ = viste._misura(vista, misura or "count")
    lookup, campo, _ = viste._percorso(vista, data, con_operatore=False)
    if not isinstance(campo, (models.DateField, models.DateTimeField)):
        raise ErroreStrumento(f"«{data}» non è un campo data.")
    qs = viste.filtra(vista, request, vista.get_queryset(request), testo, filtri).order_by()
    if qs.query.distinct:
        qs = vista.model._default_manager.filter(pk__in=qs.values("pk"))
    righe = qs.annotate(_p=UNITA[per](lookup)).values("_p").annotate(_v=espressione).order_by("_p")
    valori = {}
    for r in righe:
        if r["_p"] is not None:
            valori[_come_data(r["_p"])] = float(r["_v"] or 0)
    attuale = inizio(timezone.localdate(), per)
    passati = [p for p in valori if p < attuale]
    if not passati:
        raise ErroreStrumento("Nessun dato nei periodi passati: non c'è una storia da cui prevedere.")
    periodi, p = [], min(passati)
    while p < attuale:
        periodi.append(p)
        p = avanti(p, per)
    periodi = periodi[-MAX_PERIODI:]
    if len(periodi) < MIN_PERIODI:
        raise ErroreStrumento(f"Servono almeno {MIN_PERIODI} periodi di storia ({len(periodi)} disponibili): "
                              "prova con «per» più corto (settimana, giorno).")
    return [(p, valori.get(p, 0.0)) for p in periodi], attuale


def prevedi(storia, orizzonte):
    """[(p10, p50, p90)] per i prossimi `orizzonte` periodi dal servizio di previsione."""
    risposta = chiama("url_forecast", "/v1/forecast", {
        "series": [{"id": "serie", "values": [v for _, v in storia]}], "horizon": orizzonte,
        "quantiles": QUANTILI}, "previsione")
    try:
        quantili = risposta["forecasts"][0]["quantiles"]
        righe = list(zip(*(quantili[str(q)] for q in QUANTILI)))
    except (KeyError, IndexError, TypeError):
        raise ErroreStrumento("Risposta del servizio di previsione non valida.")
    minimo = 0.0 if all(v >= 0 for _, v in storia) else None          # serie non negative: niente previsioni < 0
    return [tuple(round(max(x, minimo) if minimo is not None else x, 2) for x in sorted(r)) for r in righe], \
        risposta.get("model", "")


def calcola_previsione(spec, contesto):
    from .strumenti import richiesta
    from .strumenti.viste import vista_per
    vista = vista_per(contesto, spec["vista"])
    storia, attuale = serie_storica(vista, richiesta.per(contesto), spec["data"], spec.get("misura", "count"),
                                    spec.get("per", "mese"), spec.get("filtri"), spec.get("testo", ""))
    futuro, modello = prevedi(storia, spec.get("orizzonte", 3))
    per = spec.get("per", "mese")
    return {"storico": [[etichetta(p, per), round(v, 2)] for p, v in storia],
            "futuro": [[etichetta(avanti(attuale, per, i), per), *q] for i, q in enumerate(futuro)],
            "totale": totale(futuro), "modello": modello}


def totale(futuro):
    """Il totale sull'orizzonte: somma delle mediane e, come intervallo prudente, somme dei 10 % e dei 90 % (più
    largo di quello vero, che richiederebbe le traiettorie). Lo calcola il codice: il modello non somma a mano."""
    return {"basso_10": round(sum(q[0] for q in futuro), 2), "mediana": round(sum(q[1] for q in futuro), 2),
            "alto_90": round(sum(q[2] for q in futuro), 2)}


# ---------- grafico ----------

def svg_previsione(dati, titolo, larghezza=720, altezza=320):
    """Storia (linea), previsione mediana (tratteggiata) e fascia 10-90 %, in SVG lato server."""
    from html import escape

    from core import svg
    storico, futuro = dati.get("storico", []), dati.get("futuro", [])
    if not storico:
        return ""
    etichette = [e for e, _ in storico] + [f[0] for f in futuro]
    massimo, passo = svg._scala(max([v for _, v in storico] + [f[3] for f in futuro] + [0]))
    sx, dx, su, giu = 56, 16, 16, 56
    w, h = larghezza - sx - dx, altezza - su - giu
    n = len(etichette)
    x = [sx + w * (i + 0.5) / n for i in range(n)]

    def y(v):
        return su + h - h * float(v) / massimo if massimo else su + h
    parti = []
    for i in range(5):
        yy = su + h - h * i * passo / massimo
        parti.append(f'<line x1="{sx}" y1="{yy:.1f}" x2="{sx + w}" y2="{yy:.1f}" stroke="{svg.GRIGLIA}"/>'
                     f'<text x="{sx - 8}" y="{yy + 4:.1f}" text-anchor="end" fill="{svg.TESTO}">'
                     f'{svg._fmt(i * passo)}</text>')
    salto = max(1, -(-n // 10))                      # al massimo una decina di etichette sull'asse
    for i, e in enumerate(etichette):
        if i % salto == 0 or i == len(storico):
            parti.append(f'<text x="{x[i]:.1f}" y="{su + h + 16}" text-anchor="end" fill="{svg.TESTO}" '
                         f'transform="rotate(-35 {x[i]:.1f} {su + h + 16})">{escape(str(e))}</text>')
    ultimo = len(storico) - 1
    if futuro:
        alto = [(x[ultimo], y(storico[-1][1]))] + [(x[ultimo + 1 + i], y(f[3])) for i, f in enumerate(futuro)]
        basso = [(x[ultimo + 1 + i], y(f[1])) for i, f in enumerate(futuro)][::-1] + [(x[ultimo], y(storico[-1][1]))]
        punti = " ".join(f"{a:.1f},{b:.1f}" for a, b in alto + basso)
        parti.append(f'<polygon points="{punti}" fill="{svg.PALETTE[1]}" fill-opacity="0.16" stroke="none">'
                     '<title>Fascia 10-90 %</title></polygon>')
        oggi = (x[ultimo] + x[ultimo + 1]) / 2
        parti.append(f'<line x1="{oggi:.1f}" y1="{su}" x2="{oggi:.1f}" y2="{su + h}" stroke="{svg.ASSE}" '
                     'stroke-dasharray="3 3"/>')
        mediana = [(x[ultimo], y(storico[-1][1]))] + [(x[ultimo + 1 + i], y(f[2])) for i, f in enumerate(futuro)]
        parti.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in mediana)}" fill="none" '
                     f'stroke="{svg.PALETTE[1]}" stroke-width="2.5" stroke-dasharray="6 4"/>')
        for i, f in enumerate(futuro):
            parti.append(f'<circle cx="{x[ultimo + 1 + i]:.1f}" cy="{y(f[2]):.1f}" r="3.5" fill="{svg.PALETTE[1]}">'
                         f'<title>{escape(str(f[0]))}: {svg._fmt(f[2])} (10-90 %: {svg._fmt(f[1])} – '
                         f'{svg._fmt(f[3])})</title></circle>')
    linea = " ".join(f"{x[i]:.1f},{y(v):.1f}" for i, (_, v) in enumerate(storico))
    parti.append(f'<polyline points="{linea}" fill="none" stroke="{svg.PALETTE[0]}" stroke-width="2.5" '
                 'stroke-linejoin="round"/>')
    parti.append(f'<line x1="{sx}" y1="{su + h}" x2="{sx + w}" y2="{su + h}" stroke="{svg.ASSE}"/>')
    return svg._svg(larghezza, altezza, titolo, "".join(parti))


# ---------- decisore ----------

TIPI_DOMANDA = {"si_no": "noul", "scelta": "choice", "punteggio": "score"}


def decidi(testo, domanda, tipo="si_no", opzioni=None):
    if tipo not in TIPI_DOMANDA:
        raise ErroreStrumento("«tipo» è si_no, scelta o punteggio.")
    q = {"type": TIPI_DOMANDA[tipo], "instructions": domanda}
    if tipo == "scelta":
        if not isinstance(opzioni, dict) or not opzioni:
            raise ErroreStrumento("Per «scelta» servono le opzioni {nome: descrizione}.")
        q["criteria"] = {str(k): str(v) for k, v in opzioni.items()}
    elif tipo == "punteggio":
        if not isinstance(opzioni, list) or not 2 <= len(opzioni) <= 10:
            raise ErroreStrumento("Per «punteggio» servono da 2 a 10 livelli in ordine, dal più basso.")
        q["criteria"] = [str(o) for o in opzioni]
    risposta = chiama("url_decider", "/v1/systemone", {"state": testo[:8000], "questions": {"d": q}}, "decisione")
    return risposta.get("answers", {}).get("d", {})
