"""Strumenti dell'assistente per le Comunicazioni (chiave "ai" del manifest): cercare e leggere le conversazioni, sempre con
ciò che l'utente può già leggere, e scrivere un messaggio, che si propone all'utente e parte solo se conferma."""
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from ai.strumenti import ErroreStrumento, Strumento, registra

from . import servizi
from .models import Canale

MASSIMO_DA_LEGGERE = 100


def _voce(m):
    return {"quando": timezone.localtime(m.creato).strftime("%d/%m/%Y %H:%M"), "autore": m.nome_mittente,
            "testo": m.corpo or m.trascrizione or "(un allegato)", "url": reverse("discuss:canale", args=[m.canale_id]) + f"?a={m.pk}"}


def _persona(testo):
    testo = testo.strip().lstrip("@")
    utenti = get_user_model().objects.filter(is_active=True)
    u = utenti.filter(username__iexact=testo).first()
    if u is not None:
        return u
    parole = testo.split()
    trovati = [x for x in utenti.filter(first_name__icontains=parole[0]) if all(p.lower() in x.get_full_name().lower() for p in parole)] if parole else []
    return trovati[0] if len(trovati) == 1 else None


def _conversazione(contesto, dove):
    """Un canale per nome (visibile all'utente) o il messaggio diretto con una persona."""
    testo = str(dove or "").strip()
    if not testo:
        raise ErroreStrumento("Indica un canale o una persona.")
    if not testo.startswith("@"):
        nome = testo.lstrip("#").strip()
        canale = servizi.visibili(contesto.utente).exclude(tipo=Canale.DIRETTO).filter(Q(nome__iexact=nome), archiviato=False).first()
        if canale is not None:
            return canale
    persona = _persona(testo)
    if persona is None or persona.pk == contesto.utente.pk:
        raise ErroreStrumento(f"Non trovo il canale o la persona «{testo}».")
    return servizi.diretto([contesto.utente, persona])


def cerca(contesto, testo):
    trovati = servizi.cerca(contesto.utente, testo)
    if not trovati:
        return "Nessun messaggio trovato."
    return [{**_voce(m), "dove": m.canale.titolo_per(contesto.utente)} for m in trovati]


def leggi(contesto, dove, quanti=30):
    canale = _conversazione(contesto, dove)
    if not servizi.puo_vedere(contesto.utente, canale):
        raise ErroreStrumento("Non puoi leggere questa conversazione.")
    elenco = servizi.messaggi(canale)[-max(1, min(int(quanti or 30), MASSIMO_DA_LEGGERE)):]
    return {"conversazione": canale.titolo_per(contesto.utente),
            "messaggi": [_voce(m) for m in elenco if m.tipo == "normale" and not m.eliminato]}


def _destinazione(contesto, dove, testo):
    if not (testo or "").strip():
        raise ErroreStrumento("Il messaggio è vuoto.")
    canale = _conversazione(contesto, dove)
    if not servizi.puo_scrivere(contesto.utente, canale):
        raise ErroreStrumento(f"Non puoi scrivere in {canale.titolo_per(contesto.utente)}.")
    return canale


def anteprima_invia(contesto, dove, testo):
    canale = _destinazione(contesto, dove, testo)
    return {"titolo": f"Scrivi a {canale.titolo_per(contesto.utente)}", "dettagli": [{"campo": "Messaggio", "dopo": testo.strip()[:1000]}]}


def invia(contesto, dove, testo):
    canale = _destinazione(contesto, dove, testo)
    m = servizi.invia(canale, contesto.utente, testo)
    return {"inviato": True, "url": reverse("discuss:canale", args=[canale.pk]) + f"?a={m.pk}"}


registra(Strumento(
    "comunicazioni_cerca", "Cerca nei messaggi delle Comunicazioni che l'utente può leggere: canali e messaggi diretti. Oltre alle "
                           "parole capisce da:nome, in:canale, ha:file, ha:link, fissato:si.",
    {"type": "object", "properties": {"testo": {"type": "string"}}, "required": ["testo"]}, cerca, permesso="discuss.view_canale", app="discuss"))
registra(Strumento(
    "comunicazioni_leggi", "Gli ultimi messaggi di un canale o del messaggio diretto con una persona, per riassumere o rispondere.",
    {"type": "object", "properties": {"dove": {"type": "string", "description": "#canale oppure @persona"},
                                      "quanti": {"type": "integer", "description": "quanti messaggi, massimo 100 (default 30)"}},
     "required": ["dove"]}, leggi, permesso="discuss.view_canale", app="discuss"))
registra(Strumento(
    "comunicazioni_scrivi", "Manda un messaggio a nome dell'utente in un canale o a una persona. Si propone all'utente, che conferma.",
    {"type": "object", "properties": {"dove": {"type": "string", "description": "#canale oppure @persona"}, "testo": {"type": "string"}},
     "required": ["dove", "testo"]}, invia, rischio="scrittura", concorrente=False, anteprima=anteprima_invia, permesso="discuss.add_messaggio", app="discuss"))
