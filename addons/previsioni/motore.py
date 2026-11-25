"""Il motore di previsione: la storia dal database con i permessi di chi guarda, i numeri dal servizio (Timestral,
quantili), l'affidabilità con la prova sul passato e il grafico SVG. Lavora su una `request` (utente e azienda), così
lo usano allo stesso modo le pagine, le schede dei moduli, Analisi e lo strumento di Ada.

Chi chiede sceglie cosa prevedere (vista, data, misura); la serie storica la costruisce il codice nel database con i
permessi dell'utente, i numeri li calcola il servizio: nessun numero della previsione viene da un modello linguistico.
Al servizio vanno solo serie di numeri con id opachi: mai nomi di prodotti, clienti o aziende.
"""
import datetime

from django.db import models
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from core.viste import interroga
from core.viste.interroga import ErroreInterrogazione

from . import servizio
from .servizio import ErrorePrevisione

UNITA = {"mese": TruncMonth, "settimana": TruncWeek, "giorno": TruncDay}
MIN_PERIODI = 6
MAX_PERIODI = 120
MAX_ORIZZONTE = 24
MAX_SERIE = 512                                  # serie per chiamata al servizio: oltre, a blocchi
QUANTILI = [0.1, 0.5, 0.9]
MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


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


# ---------- storia ----------

def vista_accessibile(request, nome):
    """La ModelView «modulo.vista» se l'utente della richiesta può vederla (personalizzata per lui)."""
    for v in interroga.viste_accessibili(request):
        if interroga.id_vista(v) == nome:
            return v
    raise ErrorePrevisione(f"Vista «{nome}» inesistente o non accessibile: usa elenco_viste per i nomi validi.")


def serie_storica(vista, request, data, misura="count", per="mese", filtri=None, testo="", lista=None):
    """([(periodo, valore)] dei periodi completi fino a quello in corso escluso, periodo in corso)."""
    if per not in UNITA:
        raise ErrorePrevisione("«per» è mese, settimana o giorno.")
    try:
        espressione, _ = interroga._misura(vista, misura or "count")
        lookup, campo, _ = interroga._percorso(vista, data, con_operatore=False)
        if not isinstance(campo, (models.DateField, models.DateTimeField)):
            raise ErrorePrevisione(f"«{data}» non è un campo data.")
        qs = interroga.filtra(vista, request, vista.get_queryset(request), testo, filtri, lista).order_by()
    except ErroreInterrogazione as e:
        raise ErrorePrevisione(str(e)) from e
    if qs.query.distinct:
        qs = vista.model._default_manager.filter(pk__in=qs.values("pk"))
    righe = qs.annotate(_p=UNITA[per](lookup)).values("_p").annotate(_v=espressione).order_by("_p")
    valori = {}
    for r in righe:
        if r["_p"] is not None:
            valori[_come_data(r["_p"])] = float(r["_v"] or 0)
    return periodi_completi(valori, per)


def periodi_completi(valori, per):
    """([(periodo, valore)] dei periodi completi, con gli zeri dei periodi vuoti, fino a quello in corso escluso;
    periodo in corso) da {inizio del periodo: valore}."""
    attuale = inizio(timezone.localdate(), per)
    passati = [p for p in valori if p < attuale]
    if not passati:
        raise ErrorePrevisione("Nessun dato nei periodi passati: non c'è una storia da cui prevedere.")
    periodi, p = [], min(passati)
    while p < attuale:
        periodi.append(p)
        p = avanti(p, per)
    periodi = periodi[-MAX_PERIODI:]
    if len(periodi) < MIN_PERIODI:
        raise ErrorePrevisione(f"Servono almeno {MIN_PERIODI} periodi di storia ({len(periodi)} disponibili): "
                               "prova con «per» più corto (settimana, giorno).")
    return [(p, valori.get(p, 0.0)) for p in periodi], attuale


# ---------- previsione dal servizio ----------

def _arrotonda(righe, storia):
    """Quantili in ordine e arrotondati; per le serie non negative niente previsioni sotto zero."""
    minimo = 0.0 if all(v >= 0 for _, v in storia) else None
    return [tuple(round(max(x, minimo) if minimo is not None else x, 2) for x in sorted(r)) for r in righe]


def prevedi_molte(storie, orizzonte):
    """({chiave: [(p10, p50, p90)]} per i prossimi `orizzonte` periodi di ogni storia, nome del modello). Al servizio
    vanno solo i valori con id opachi (s1, s2…), al massimo MAX_SERIE per chiamata; il risultato torna per chiave."""
    chiavi, futuri, modello = list(storie), {}, ""
    for primo in range(0, len(chiavi), MAX_SERIE):
        blocco = {f"s{primo + i + 1}": chiave for i, chiave in enumerate(chiavi[primo:primo + MAX_SERIE])}
        risposta = servizio.chiama("/v1/forecast", {
            "series": [{"id": sid, "values": [v for _, v in storie[chiave]]} for sid, chiave in blocco.items()],
            "horizon": orizzonte, "quantiles": QUANTILI})
        try:
            per_id = {f["id"]: f["quantiles"] for f in risposta["forecasts"]}
            for sid, chiave in blocco.items():
                futuri[chiave] = _arrotonda(list(zip(*(per_id[sid][str(q)] for q in QUANTILI))), storie[chiave])
            modello = modello or risposta.get("model", "")
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ErrorePrevisione("Risposta del servizio di previsione non valida.")
    return futuri, modello


def prevedi(storia, orizzonte):
    """([(p10, p50, p90)] per i prossimi `orizzonte` periodi dal servizio di previsione, nome del modello)."""
    futuri, modello = prevedi_molte({"serie": storia}, orizzonte)
    return futuri["serie"], modello


def calcola_previsione(spec, request, vista=None):
    """La previsione di una specifica (vista, data, misura, per, orizzonte, filtri, testo, lista, oppure
    misura_aziendale) per l'utente della richiesta: {"storico", "futuro", "totale", "modello", "affidabilita"}.
    `vista`, se c'è, è la ModelView già scelta da chi chiama (per esempio Ada, con le viste della sua chat) e prende il
    posto della ricerca per nome tra quelle accessibili all'utente."""
    per = spec.get("per", "mese")
    if spec.get("misura_aziendale"):                     # la storia di una misura aziendale (note di credito comprese)
        from core import misure
        if per not in UNITA:
            raise ErrorePrevisione("«per» è mese, settimana o giorno.")
        try:
            valori = {inizio(d, per): v for d, v in misure.storia(spec["misura_aziendale"], request, per).items()}
        except ErroreInterrogazione as e:
            raise ErrorePrevisione(str(e)) from e
        if not valori:
            raise ErrorePrevisione("Nessun dato nei periodi passati: non c'è una storia da cui prevedere.")
        storia, attuale = periodi_completi(valori, per)
    else:
        if vista is None:
            vista = vista_accessibile(request, spec["vista"])
        storia, attuale = serie_storica(vista, request, spec["data"], spec.get("misura", "count"), per,
                                        spec.get("filtri"), spec.get("testo", ""), spec.get("lista"))
    futuro, modello = prevedi(storia, spec.get("orizzonte", 3))
    return {"storico": [[etichetta(p, per), round(v, 2)] for p, v in storia],
            "futuro": [[etichetta(avanti(attuale, per, i), per), *q] for i, q in enumerate(futuro)],
            "totale": totale(futuro), "modello": modello,
            "affidabilita": affidabilita(storia, futuro, spec.get("orizzonte", 3), per)}


# ---------- affidabilità di una previsione: calcolata dal codice, non dichiarata da un modello linguistico ----------
STORIA_SOLIDA, STORIA_MINIMA = 24, 12          # periodi di storia
LARGHEZZA_BUONA, LARGHEZZA_MASSIMA = 0.5, 1.0  # ampiezza media dell'intervallo 10-90 % rispetto alla mediana
ERRORE_BUONO, ERRORE_MASSIMO = 0.15, 0.35      # errore medio della prova sul passato (backtest)
PERIODI = {"mese": ("mese", "mesi"), "settimana": ("settimana", "settimane"), "giorno": ("giorno", "giorni")}


def affidabilita(storia, futuro, orizzonte, per="mese"):
    """Alta, media o bassa da tre misure: quanta storia c'è, quanto è largo l'intervallo 10-90 %, e quanto avrebbe
    sbagliato il modello sugli ultimi periodi già noti (la stessa previsione rifatta senza di loro: backtest)."""
    uno, molti = PERIODI.get(per, ("periodo", "periodi"))
    n = len(storia)
    larghezze = [(alto - basso) / abs(mediana) for basso, mediana, alto in futuro if mediana]
    larghezza = sum(larghezze) / len(larghezze) if larghezze else None
    errore, provati = None, min(3, orizzonte)
    if n - provati >= MIN_PERIODI:
        try:
            prova, _ = prevedi(storia[:-provati], provati)
            scarti = [abs(p[1] - v) / abs(v) for p, (_, v) in zip(prova, storia[-provati:]) if v]
            errore = sum(scarti) / len(scarti) if scarti else None
        except ErrorePrevisione:
            errore = None
    giudizi = ["buono" if n >= STORIA_SOLIDA else "debole" if n < STORIA_MINIMA else "medio"]
    motivi = [f"Storia: {n} {uno if n == 1 else molti}" + ("" if n >= STORIA_SOLIDA else
              f" (per una previsione solida ne servono almeno {STORIA_SOLIDA})")]
    if larghezza is not None:
        giudizi.append("buono" if larghezza <= LARGHEZZA_BUONA else "debole" if larghezza > LARGHEZZA_MASSIMA else "medio")
        motivi.append(f"Intervallo 10-90 %: in media ±{round(larghezza * 50)}% della mediana")
    if errore is not None:
        giudizi.append("buono" if errore <= ERRORE_BUONO else "debole" if errore > ERRORE_MASSIMO else "medio")
        motivi.append(f"Errore sugli ultimi {provati} {uno if provati == 1 else molti} già noti: {round(errore * 100)}% "
                      "(la previsione rifatta senza di loro, confrontata con il vero)")
    livello = "bassa" if "debole" in giudizi else "alta" if errore is not None and set(giudizi) == {"buono"} else "media"
    return {"livello": livello, "periodi_di_storia": n, "larghezza": round(larghezza, 3) if larghezza is not None else None,
            "errore": round(errore, 3) if errore is not None else None, "motivi": motivi}


def totale(futuro):
    """Il totale sull'orizzonte: somma delle mediane e, come intervallo prudente, somme dei 10 % e dei 90 % (più
    largo di quello vero, che richiederebbe le traiettorie). Lo calcola il codice: nessuno somma a mano."""
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
