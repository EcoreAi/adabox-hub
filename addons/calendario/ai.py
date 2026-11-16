"""Strumenti dell'assistente AI per il calendario (chiave "ai" del manifest)."""
import datetime

from django.utils import timezone

from ai.strumenti import ErroreStrumento, Strumento, registra, richiesta
from ai.strumenti.viste import vista_per

MAX_GIORNI = 62


def _data(testo, default):
    try:
        return datetime.date.fromisoformat(testo) if testo else default
    except (TypeError, ValueError):
        raise ErroreStrumento(f"«{testo}» non è una data AAAA-MM-GG.")


def agenda(contesto, da="", a=""):
    """Gli eventi che l'utente vede tra due date (comprese), anche quelli iniziati prima e ancora in corso."""
    inizio = _data(da, timezone.localdate())
    fine = _data(a, inizio + datetime.timedelta(days=6))
    if fine < inizio or (fine - inizio).days > MAX_GIORNI:
        raise ErroreStrumento(f"Periodo non valido: al massimo {MAX_GIORNI} giorni, «a» non prima di «da».")
    vista = vista_per(contesto, "calendario.eventi")
    request = richiesta.per(contesto)
    eventi = (vista.get_queryset(request).filter(inizio__date__lte=fine, fine__date__gte=inizio)
              .order_by("inizio").prefetch_related("partecipanti")[:200])
    adesso = timezone.now()

    def stato(e):                        # rispetto ad adesso, calcolato qui: il modello non deve confrontare gli orari
        return "passato" if e.fine <= adesso else "in corso" if e.inizio <= adesso else "da venire"
    righe = [{
        "id": e.pk, "titolo": e.titolo, "url": vista.url("dettaglio", pk=e.pk), "stato": stato(e),
        "inizio": timezone.localtime(e.inizio).strftime("%Y-%m-%d %H:%M"),
        "fine": timezone.localtime(e.fine).strftime("%Y-%m-%d %H:%M"), "tutto_il_giorno": e.tutto_il_giorno,
        "luogo": e.luogo, "partecipanti": [p.get_full_name() or p.username for p in e.partecipanti.all()]}
        for e in eventi]
    conteggio = {s: sum(r["stato"] == s for r in righe) for s in ("passato", "in corso", "da venire")}
    return {"da": inizio.isoformat(), "a": fine.isoformat(), "adesso": timezone.localtime(adesso).strftime("%Y-%m-%d %H:%M"),
            "sintesi": sintesi(conteggio), **da_ricordare(conteggio), "conteggio": conteggio, "eventi": righe}


def da_ricordare(conteggio):
    """Se ci sono appuntamenti già passati e altri da fare, la risposta deve dire quanti sono i passati: se il modello
    lo tace, il motore aggiunge questa frase (ai.guardia.da_ricordare)."""
    n = conteggio["passato"]
    if not n or not (conteggio["in corso"] or conteggio["da venire"]):
        return {}
    testo = f"{'Ne è già passato uno' if n == 1 else f'Ne sono già passati {n}'} nel periodo: vuoi sentirli?"
    return {"da_ricordare": {"testo": testo, "segno": n}}


def sintesi(conteggio):
    """La frase dei numeri, scritta qui: il modello la riporta invece di contare (e di tacere i passati)."""
    totale = sum(conteggio.values())
    if not totale:
        return "Nessun appuntamento nel periodo."
    def quanti(n, uno, molti):
        return f"{n} {uno if n == 1 else molti}"
    parti = [quanti(conteggio["passato"], "già passato", "già passati"),
             "nessuno in corso" if not conteggio["in corso"] else quanti(conteggio["in corso"], "in corso", "in corso"),
             quanti(conteggio["da venire"], "da venire", "da venire")]
    return f"{quanti(totale, 'appuntamento', 'appuntamenti')} nel periodo: " + ", ".join(parti) + "."


registra(Strumento(
    "calendario_agenda", "Gli appuntamenti e le riunioni del calendario tra due date (default: i prossimi 7 giorni), "
                         "compresi quelli già iniziati e ancora in corso. Ogni evento ha uno stato rispetto ad adesso "
                         "(passato, in corso, da venire); «sintesi» dice quanti sono per stato. Riporta sempre i numeri "
                         "della sintesi, anche quelli già passati (non dire «ci sono 4» se 6 sono già passati). Per «che "
                         "appuntamenti ho» elenca quelli in corso e da venire; dei passati di' solo quanti sono e chiedi "
                         "se vuole il dettaglio, a meno che l'utente chieda proprio quelli.",
    {"type": "object", "properties": {"da": {"type": "string", "description": "AAAA-MM-GG, default oggi"},
                                      "a": {"type": "string", "description": "AAAA-MM-GG, compresa"}},
     "required": []}, agenda, permesso="calendario.view_evento"))
