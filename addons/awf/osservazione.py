"""Rete di sicurezza locale: quando le scritture degli agenti restano ferme.

Agate ha già le sue regole e la sua osservazione; questa è una seconda rete, in casa. Se l'ultimo stato
dell'ingaggio ricevuto dalla fabbrica dice che l'ingaggio è in osservazione, bloccato o non attivo, le scritture e
le operazioni irreversibili non girano (le letture sì) e la chiamata si registra con «cosa sarebbe successo».
Lo stato è quello dell'ultimo battito riuscito: un battito che non arriva lascia valido l'ultimo stato noto."""
import re

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core import parametri

from .models import Collegamento

CODICE_RE = re.compile(r"^[a-z0-9_.-]{1,60}$")


def _codice(valore, altrimenti):
    return valore if isinstance(valore, str) and CODICE_RE.match(valore) else altrimenti


def motivo(collegamento=None):
    """Perché le scritture sono ferme ora; stringa vuota se possono girare."""
    if parametri.leggi("awf.osservazione"):
        return "osservazione impostata nelle impostazioni di AWF"
    collegamento = collegamento or Collegamento.attuale()
    if not collegamento.collegato:
        return "non collegato alla fabbrica"
    ingaggio = collegamento.ingaggio
    bloccato = ingaggio.get("blocked")
    if bloccato:
        codice = bloccato.get("code") if isinstance(bloccato, dict) else None
        return f"ingaggio bloccato ({_codice(codice, 'senza codice')})"
    if ingaggio.get("status") != "active":
        return f"ingaggio non attivo (stato: {_codice(ingaggio.get('status'), 'sconosciuto')})"
    grezzo = ingaggio.get("observe_until")
    try:
        fino = parse_datetime(grezzo) if isinstance(grezzo, str) else None
    except ValueError:
        fino = None
    if fino is not None and timezone.is_naive(fino):
        fino = timezone.make_aware(fino)
    if fino is not None and fino > timezone.now():
        return f"ingaggio in osservazione fino al {timezone.localtime(fino):%d/%m/%Y %H:%M}"
    return ""
