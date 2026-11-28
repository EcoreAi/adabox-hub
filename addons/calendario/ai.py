"""Strumenti dell'assistente AI per il calendario (chiave "ai" del manifest)."""
import datetime

from django.db.models import Q
from django.utils import timezone

from ai.strumenti import ErroreStrumento, Strumento, registra, richiesta
from ai.strumenti.viste import vista_per

MAX_GIORNI = 62
MAX_EVENTI = 200
DI = ("miei", "tutti")


def _data(testo, default):
    try:
        return datetime.date.fromisoformat(testo) if testo else default
    except (TypeError, ValueError):
        raise ErroreStrumento(f"«{testo}» non è una data AAAA-MM-GG.")


def _nome(utente):
    return (utente.get_full_name() or utente.username) if utente else ""


def agenda(contesto, da="", a="", di="miei"):
    """Gli appuntamenti tra due date (comprese), anche quelli iniziati prima e ancora in corso. Di default quelli di chi
    chiede (organizzatore o partecipante), come la misura «appuntamenti»: prima erano tutti quelli che vede, e Ada
    diceva «hai sei appuntamenti» elencando quelli dei colleghi. Con di="tutti" quelli di tutti, ognuno con «tuo»."""
    di = str(di or "miei").strip().lower()
    if di not in DI:
        raise ErroreStrumento('«di» è "miei" (gli appuntamenti dell\'utente, il default) oppure "tutti" (quelli di tutti '
                              'i colleghi che vede).')
    inizio = _data(da, timezone.localdate())
    fine = _data(a, inizio + datetime.timedelta(days=6))
    if fine < inizio or (fine - inizio).days > MAX_GIORNI:
        raise ErroreStrumento(f"Periodo non valido: al massimo {MAX_GIORNI} giorni, «a» non prima di «da».")
    vista = vista_per(contesto, "calendario.eventi")
    request = richiesta.per(contesto)
    visibili = vista.get_queryset(request).filter(inizio__date__lte=fine, fine__date__gte=inizio)
    miei = set(visibili.filter(Q(organizzatore=contesto.utente) | Q(partecipanti=contesto.utente)).values_list("pk", flat=True))
    periodo = visibili.filter(pk__in=miei) if di == "miei" else visibili
    adesso = timezone.now()
    # contati nel database su tutto il periodo: l'elenco si ferma a MAX_EVENTI, il conteggio no
    conteggio = {"passato": periodo.filter(fine__lte=adesso).count(),
                 "in corso": periodo.filter(inizio__lte=adesso, fine__gt=adesso).count(),
                 "da venire": periodo.filter(inizio__gt=adesso).count()}
    eventi = periodo.order_by("inizio", "pk").select_related("organizzatore").prefetch_related("partecipanti")[:MAX_EVENTI]

    def stato(e):                        # rispetto ad adesso, calcolato qui: il modello non deve confrontare gli orari
        return "passato" if e.fine <= adesso else "in corso" if e.inizio <= adesso else "da venire"
    righe = [{
        "id": e.pk, "titolo": e.titolo, "url": vista.url("dettaglio", pk=e.pk), "stato": stato(e),
        "inizio": timezone.localtime(e.inizio).strftime("%Y-%m-%d %H:%M"),
        "fine": timezone.localtime(e.fine).strftime("%Y-%m-%d %H:%M"), "tutto_il_giorno": e.tutto_il_giorno,
        "luogo": e.luogo, "organizzatore": _nome(e.organizzatore),
        "partecipanti": [_nome(p) for p in e.partecipanti.all()], **({"tuo": e.pk in miei} if di == "tutti" else {})}
        for e in eventi]
    risultato = {"da": inizio.isoformat(), "a": fine.isoformat(), "di": di,
                 "adesso": timezone.localtime(adesso).strftime("%Y-%m-%d %H:%M"),
                 "sintesi": sintesi(conteggio), **da_ricordare(conteggio), "conteggio": conteggio, "eventi": righe}
    totale = sum(conteggio.values())
    if totale > len(righe):
        risultato["nota"] = f"Elencati i primi {len(righe)} di {totale} appuntamenti: per gli altri restringi le date."
    return risultato


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
                         "compresi quelli già iniziati e ancora in corso. Di default solo quelli dell'utente (organizzatore "
                         "o partecipante); con di=\"tutti\" quelli di tutti i colleghi che vede, ognuno con «tuo» vero o "
                         "falso: usalo solo se chiede il calendario di tutti o di un collega, e di' di chi sono. Ogni evento "
                         "ha uno stato rispetto ad adesso (passato, in corso, da venire); «sintesi» dice quanti sono per "
                         "stato. Riporta sempre i numeri della sintesi, anche quelli già passati (non dire «ci sono 4» se 6 "
                         "sono già passati). Per «che appuntamenti ho» elenca quelli in corso e da venire; dei passati di' "
                         "solo quanti sono e chiedi se vuole il dettaglio, a meno che l'utente chieda proprio quelli. Sono "
                         "appuntamenti, non le attività da fare (compiti, cose da fare con una scadenza): per «che attività "
                         "ho», «cosa devo fare» cerca la vista delle attività con elenco_viste.",
    {"type": "object", "properties": {"da": {"type": "string", "description": "AAAA-MM-GG, default oggi"},
                                      "a": {"type": "string", "description": "AAAA-MM-GG, compresa"},
                                      "di": {"type": "string", "enum": list(DI),
                                             "description": "miei (default): gli appuntamenti dell'utente; tutti: quelli di tutti i colleghi che vede"}},
     "required": []}, agenda, permesso="calendario.view_evento"))
