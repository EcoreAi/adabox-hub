"""Lavori in background nel database: accoda, worker, ritentativi (e pianificazioni, vedi sotto)."""
import importlib
import json
import logging
import traceback
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .models import Lavoro

log = logging.getLogger("core.lavori")
BACKOFF = [60, 300, 1800]           # secondi prima del 2°, 3°, 4°... tentativo
BLOCCATO_DOPO = timedelta(minutes=30)


def risolvi(percorso):
    modulo, _, nome = percorso.rpartition(".")
    return getattr(importlib.import_module(modulo), nome)


def accoda(funzione, *, ritardo=0, max_tentativi=3, azienda=None, utente=None, **argomenti):
    """Accoda `funzione` (percorso puntato) con argomenti JSON. Con LAVORI_SINCRONI e senza ritardo
    la esegue subito, nello stesso processo; un errore non risale al chiamante ma va nel lavoro."""
    json.dumps(argomenti)                       # TypeError subito se non serializzabili
    lavoro = Lavoro.objects.create(
        funzione=funzione, argomenti=argomenti, max_tentativi=max_tentativi, azienda=azienda, utente=utente,
        esegui_dopo=timezone.now() + timedelta(seconds=ritardo))
    if settings.LAVORI_SINCRONI and not ritardo:
        _prendi(lavoro)
        _esegui(lavoro, sincrono=True)
    return lavoro


def _prendi(lavoro):
    lavoro.stato, lavoro.iniziato, lavoro.tentativi = Lavoro.IN_CORSO, timezone.now(), lavoro.tentativi + 1
    lavoro.save(update_fields=["stato", "iniziato", "tentativi"])


def _esegui(lavoro, sincrono=False):
    try:
        with transaction.atomic():
            risultato = risolvi(lavoro.funzione)(**lavoro.argomenti)
    except Exception:
        lavoro.errore = traceback.format_exc()[-8000:]
        log.exception("lavoro %s fallito (tentativo %s)", lavoro, lavoro.tentativi)
        if sincrono or lavoro.tentativi >= lavoro.max_tentativi:
            lavoro.stato, lavoro.finito = Lavoro.FALLITO, timezone.now()
        else:
            attesa = BACKOFF[min(lavoro.tentativi - 1, len(BACKOFF) - 1)]
            lavoro.stato, lavoro.esegui_dopo = Lavoro.IN_CODA, timezone.now() + timedelta(seconds=attesa)
    else:
        lavoro.stato, lavoro.finito, lavoro.errore = Lavoro.FATTO, timezone.now(), ""
        lavoro.risultato = "" if risultato is None else str(risultato)[:2000]
    lavoro.save(update_fields=["stato", "finito", "errore", "risultato", "esegui_dopo"])
    return lavoro


def esegui_uno():
    """Prende il primo lavoro pronto (skip_locked dove c'è: più worker in parallelo) e lo esegue.
    Restituisce il lavoro o None se la coda è vuota."""
    with transaction.atomic():
        qs = Lavoro.objects.filter(stato=Lavoro.IN_CODA, esegui_dopo__lte=timezone.now()).order_by("esegui_dopo", "pk")
        if connection.features.has_select_for_update_skip_locked:
            qs = qs.select_for_update(skip_locked=True)
        lavoro = qs.first()
        if lavoro is None:
            return None
        _prendi(lavoro)
    return _esegui(lavoro)


def sblocca():
    """Rimette in coda i lavori rimasti 'in corso' da troppo (worker morto a metà)."""
    return Lavoro.objects.filter(stato=Lavoro.IN_CORSO, iniziato__lt=timezone.now() - BLOCCATO_DOPO).update(
        stato=Lavoro.IN_CODA, esegui_dopo=timezone.now())


def riprova(lavoro):
    lavoro.stato, lavoro.esegui_dopo, lavoro.tentativi, lavoro.errore = Lavoro.IN_CODA, timezone.now(), 0, ""
    lavoro.save(update_fields=["stato", "esegui_dopo", "tentativi", "errore"])
