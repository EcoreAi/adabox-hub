"""Streaming di un turno con Server-Sent Events: segue il turno nel database (testo, avanzamento, fine).

Django 5.2 bufferizza le risposte in streaming se il tipo di generatore non corrisponde al server: sotto ASGI
(il servizio `stream` in produzione) serve un generatore asincrono, sotto WSGI (runserver, test) uno sincrono.
L'id di ogni evento di testo è la posizione nel testo: se la connessione cade, il browser riprende da lì."""
import asyncio
import json
import time

from asgiref.sync import sync_to_async
from django.contrib.auth.decorators import login_required
from django.core.handlers.asgi import ASGIRequest
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from .models import MessaggioChat, Turno

INTERVALLO = 0.15                       # secondi tra due letture del turno
DURATA_MASSIMA = 600                    # dopo, il browser si ricollega da solo
BATTITO = 15                            # commento periodico: tiene viva la connessione attraverso i proxy


def _evento(nome, dati, id_evento=None):
    testa = f"id: {id_evento}\n" if id_evento is not None else ""
    return f"{testa}event: {nome}\ndata: {json.dumps(dati, ensure_ascii=False)}\n\n"


class _Stato:
    def __init__(self, posizione=0):
        self.posizione, self.avanzamento = posizione, -1


def _passo(turno_id, stato):
    """(eventi, finito) dallo stato attuale del turno."""
    turno = Turno.objects.filter(pk=turno_id).only("testo", "avanzamento", "stato", "conversazione_id").first()
    if turno is None:
        return [_evento("fine", {"stato": "errore", "html": ""})], True
    eventi = []
    if len(turno.avanzamento) != stato.avanzamento:
        stato.avanzamento = len(turno.avanzamento)
        eventi.append(_evento("avanzamento", turno.avanzamento))
    if not turno.concluso and len(turno.testo) > stato.posizione:
        eventi.append(_evento("testo", {"delta": turno.testo[stato.posizione:]}, len(turno.testo)))
        stato.posizione = len(turno.testo)
    if turno.concluso:
        messaggio = (MessaggioChat.objects.filter(conversazione_id=turno.conversazione_id,
                                                  ruolo=MessaggioChat.ASSISTENTE).order_by("-pk").first())
        html = render_to_string("ai/_messaggi.html", {"messaggi": [messaggio]}) if messaggio else ""
        eventi.append(_evento("fine", {"stato": turno.stato, "html": html}))
        return eventi, True
    return eventi, False


def _sincrono(turno_id, stato):
    inizio = ultimo = time.monotonic()
    while time.monotonic() - inizio < DURATA_MASSIMA:
        eventi, finito = _passo(turno_id, stato)
        yield from eventi
        if finito:
            return
        if time.monotonic() - ultimo > BATTITO:
            ultimo = time.monotonic()
            yield ": battito\n\n"
        time.sleep(INTERVALLO)


async def _asincrono(turno_id, stato):
    passo = sync_to_async(_passo, thread_sensitive=False)
    inizio = ultimo = time.monotonic()
    while time.monotonic() - inizio < DURATA_MASSIMA:
        eventi, finito = await passo(turno_id, stato)
        for e in eventi:
            yield e
        if finito:
            return
        if time.monotonic() - ultimo > BATTITO:
            ultimo = time.monotonic()
            yield ": battito\n\n"
        await asyncio.sleep(INTERVALLO)


@require_GET
@login_required
def flusso(request, pk):
    turno = get_object_or_404(Turno, pk=pk, conversazione__utente=request.user)
    ultimo = request.headers.get("Last-Event-ID", "")
    stato = _Stato(int(ultimo) if ultimo.isdigit() else 0)
    generatore = _asincrono(turno.pk, stato) if isinstance(request, ASGIRequest) else _sincrono(turno.pk, stato)
    risposta = StreamingHttpResponse(generatore, content_type="text/event-stream; charset=utf-8")
    risposta["Cache-Control"] = "no-cache"
    risposta["X-Accel-Buffering"] = "no"
    return risposta
