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
    return {"da": inizio.isoformat(), "a": fine.isoformat(), "eventi": [{
        "id": e.pk, "titolo": e.titolo, "url": vista.url("dettaglio", pk=e.pk),
        "inizio": timezone.localtime(e.inizio).strftime("%Y-%m-%d %H:%M"),
        "fine": timezone.localtime(e.fine).strftime("%Y-%m-%d %H:%M"), "tutto_il_giorno": e.tutto_il_giorno,
        "luogo": e.luogo, "partecipanti": [p.get_full_name() or p.username for p in e.partecipanti.all()]}
        for e in eventi]}


registra(Strumento(
    "calendario_agenda", "Gli appuntamenti e le riunioni del calendario tra due date (default: i prossimi 7 giorni), "
                         "compresi quelli già iniziati e ancora in corso.",
    {"type": "object", "properties": {"da": {"type": "string", "description": "AAAA-MM-GG, default oggi"},
                                      "a": {"type": "string", "description": "AAAA-MM-GG, compresa"}},
     "required": []}, agenda, permesso="calendario.view_evento"))
