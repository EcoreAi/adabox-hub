"""Spedizione degli avvisi: corpo JSON firmato, tentativi affidati ai lavori, webhook spento se fallisce troppe volte."""
import datetime
import hashlib
import hmac
import json
import logging
import time

from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from core import rete

from .models import ConsegnaWebhook, Webhook

log = logging.getLogger("connettori.consegne")
MAX_FALLIMENTI_DI_FILA = 20
GIORNI_DI_STORICO = 30
HTTP = None                                             # solo per i test: un client httpx finto


class NonConsegnata(RuntimeError):
    """Fa ritentare il lavoro più tardi."""


def firma(segreto, istante, corpo):
    return hmac.new(segreto.encode(), f"{istante}.".encode() + corpo, hashlib.sha256).hexdigest()


def _dati(consegna):
    """I dati da spedire; None se il record non c'è più (l'eliminazione ha il suo avviso)."""
    if consegna.istantanea is not None:
        return consegna.istantanea
    from core.api.modelli import serializza
    from core.viste import registry
    modello = consegna.content_type.model_class() if consegna.content_type_id else None
    vista = registry.per_modello(modello) if modello else None
    obj = modello._default_manager.filter(pk=consegna.object_id).first() if vista else None
    return serializza(vista, obj) if obj is not None else None


def _esito_negativo(consegna, errore, risposta=None):
    webhook = consegna.webhook
    ConsegnaWebhook.objects.filter(pk=consegna.pk).update(stato=ConsegnaWebhook.FALLITA if consegna.tentativi >= 5 else ConsegnaWebhook.IN_CODA,
                                                          tentativi=consegna.tentativi, errore=errore[:300], risposta=risposta)
    fallimenti = webhook.fallimenti_di_fila + 1
    if fallimenti >= MAX_FALLIMENTI_DI_FILA and webhook.attivo:
        Webhook.objects.filter(pk=webhook.pk).update(fallimenti_di_fila=fallimenti, attivo=False, disattivato_il=timezone.now())
        log.warning("webhook %s spento dopo %s fallimenti di fila", webhook.pk, fallimenti)
    else:
        Webhook.objects.filter(pk=webhook.pk).update(fallimenti_di_fila=fallimenti)
    raise NonConsegnata(errore)


def invia(consegna_id):
    consegna = ConsegnaWebhook.objects.select_related("webhook", "content_type").filter(pk=consegna_id).first()
    if consegna is None or consegna.stato != ConsegnaWebhook.IN_CODA:
        return None
    webhook = consegna.webhook
    if not webhook.attivo:
        ConsegnaWebhook.objects.filter(pk=consegna.pk).update(stato=ConsegnaWebhook.SALTATA, errore="webhook disattivato")
        return "saltata"
    dati = _dati(consegna)
    if dati is None:
        ConsegnaWebhook.objects.filter(pk=consegna.pk).update(stato=ConsegnaWebhook.SALTATA, errore="record non più presente")
        return "saltata"
    consegna.tentativi += 1
    corpo = json.dumps({"id": str(consegna.uid), "evento": consegna.evento, "azienda": consegna.azienda_id,
                        "creato": consegna.creata.isoformat(), "dati": dati}, cls=DjangoJSONEncoder).encode()
    istante = int(time.time())
    intestazioni = {"Content-Type": "application/json", "User-Agent": "adabox-webhook/1.0",
                    "X-Adabox-Evento": consegna.evento, "X-Adabox-Consegna": str(consegna.uid),
                    "X-Adabox-Firma": f"t={istante},v1={firma(webhook.segreto(), istante, corpo)}"}
    try:
        stato = rete.post_sicuro(webhook.url, corpo, intestazioni, http_client=HTTP)
    except rete.Rifiutato as e:
        _esito_negativo(consegna, f"Indirizzo rifiutato: {e}")
    except Exception as e:  # noqa: BLE001 - qualunque errore di rete si ritenta
        _esito_negativo(consegna, f"{type(e).__name__}: {e}")
    if not 200 <= stato < 300:
        _esito_negativo(consegna, f"Risposta {stato}", stato)
    ConsegnaWebhook.objects.filter(pk=consegna.pk).update(stato=ConsegnaWebhook.CONSEGNATA, tentativi=consegna.tentativi, risposta=stato,
                                                          errore="", consegnata_il=timezone.now())
    Webhook.objects.filter(pk=webhook.pk).update(fallimenti_di_fila=0)
    return "consegnata"


invia.senza_transazione = True                          # la rete non deve tenere aperta una transazione


def pulisci():
    limite = timezone.now() - datetime.timedelta(days=GIORNI_DI_STORICO)
    return ConsegnaWebhook.objects.filter(creata__lt=limite).exclude(stato=ConsegnaWebhook.IN_CODA).delete()[0]
