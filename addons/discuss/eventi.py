"""Tempo reale: gli eventi si scrivono nel database, ogni browser li legge da un'unica connessione SSE.

Sotto ASGI (servizio `stream`) la connessione resta aperta. Sotto WSGI, cioè quando nginx non instrada /discuss/eventi/
verso `stream` (una versione vecchia della configurazione), si risponde con ciò che c'è e si chiude: il browser si
ricollega da solo dopo `retry`, così non si tiene occupato un worker."""
import asyncio
import datetime
import json
import time

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.handlers.asgi import ASGIRequest
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Canale, Evento, Iscrizione

INTERVALLO = 1.0                        # secondi tra due letture
DURATA_MASSIMA = 280                    # dopo, il browser si ricollega da solo
BATTITO = 15
RIPROVA_MS = 3000
GIORNI_DI_VITA = 1


def emetti(tipo, canale=None, utente=None, **dati):
    evento = Evento.objects.create(tipo=tipo, canale=canale, utente=utente, dati=dati)
    if tipo == "notifica" and utente is not None:          # anche sul telefono, se l'utente l'ha attivato
        from core import push
        push.accoda(utente, dati.get("titolo", ""), dati.get("testo", ""), dati.get("url", "/"))
    return evento


def ultimo_id():
    return Evento.objects.order_by("-pk").values_list("pk", flat=True).first() or 0


def nuovi_per(utente_id, dopo, corrente=None):
    """Gli eventi per questa persona: i suoi e quelli dei canali in cui è iscritta o che sta guardando."""
    iscritti = Iscrizione.objects.filter(utente_id=utente_id).values("canale_id")
    filtro = Q(utente_id=utente_id) | Q(utente__isnull=True, canale_id__in=iscritti)
    if corrente:
        filtro |= Q(utente__isnull=True, canale_id=corrente)
    return list(Evento.objects.filter(filtro, pk__gt=dopo).order_by("pk")[:100])


def _testo(evento):
    dati = {"tipo": evento.tipo, "canale": evento.canale_id, **evento.dati}
    return f"id: {evento.pk}\nevent: discuss\ndata: {json.dumps(dati, ensure_ascii=False)}\n\n"


def _passo(utente_id, stato, corrente):
    elenco = nuovi_per(utente_id, stato["dopo"], corrente)
    if elenco:
        stato["dopo"] = elenco[-1].pk
    return [_testo(e) for e in elenco]


def _sincrono(utente_id, stato, corrente):
    yield f"retry: {RIPROVA_MS}\n\n"
    yield from _passo(utente_id, stato, corrente)


async def _asincrono(utente_id, stato, corrente):
    passo = sync_to_async(_passo, thread_sensitive=False)
    yield f"retry: {RIPROVA_MS}\n\n"
    inizio = ultimo = time.monotonic()
    while time.monotonic() - inizio < DURATA_MASSIMA:
        for testo in await passo(utente_id, stato, corrente):
            yield testo
        if time.monotonic() - ultimo > BATTITO:
            ultimo = time.monotonic()
            yield ": battito\n\n"
        await asyncio.sleep(INTERVALLO)


@require_GET
@login_required
def flusso(request):
    if not request.user.has_perm("discuss.view_canale"):
        raise PermissionDenied
    ripresa = request.headers.get("Last-Event-ID") or request.GET.get("dopo", "")
    stato = {"dopo": int(ripresa) if ripresa.isdigit() else ultimo_id()}
    corrente = request.GET.get("canale", "")
    corrente = int(corrente) if corrente.isdigit() else None
    if corrente:
        from . import servizi
        canale = Canale.objects.filter(pk=corrente).first()
        corrente = corrente if canale is not None and servizi.puo_vedere(request.user, canale) else None
    generatore = (_asincrono if isinstance(request, ASGIRequest) else _sincrono)(request.user.pk, stato, corrente)
    risposta = StreamingHttpResponse(generatore, content_type="text/event-stream; charset=utf-8")
    risposta["Cache-Control"] = "no-cache"
    risposta["X-Accel-Buffering"] = "no"
    return risposta


def pulisci():
    """Lavoro pianificato: gli eventi servono solo a chi è collegato."""
    limite = timezone.now() - datetime.timedelta(days=GIORNI_DI_VITA)
    return f"eventi eliminati: {Evento.objects.filter(creato__lt=limite).delete()[0]}"
