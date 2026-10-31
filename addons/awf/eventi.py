"""Eventi verso la fabbrica: un record assegnato a un agente (§5 del contratto). Solo nome, id e agente, mai testo.

Quando un'attività del kernel (`core.AttivitaPianificata`, il pannello «Pianifica un'attività» del chatter) o un
record con il campo `assegnatario` (es. le attività di To-Do, i ticket) viene assegnato a un utente agente, dopo il
commit si accoda un lavoro che manda alla fabbrica:

    {"type": "record.assigned", "model": "<vista>", "record_id": <id>, "agent": "<nome dell'agente>"}

`model` è il nome della vista del record (es. `todo.attivita`, `crm.lead`): è quello che gli strumenti MCP
accettano come `vista`, così l'agente legge il record con `leggi_record` passando da Agate. Se il modello non ha una
vista si manda l'etichetta del modello (`app.modello`). Per un'attività del kernel il record è quello su cui è
pianificata.

Un errore (fabbrica giù, non collegato, troppi eventi) non tocca mai il salvataggio dell'utente: si scrive nel log
e nel lavoro, che il worker ritenta."""
import logging

from django.conf import settings
from django.db import transaction

from .models import Agente

log = logging.getLogger("awf.eventi")
_ha_assegnatario = {}


def _campo_utente(modello):
    """Vero se il modello ha un campo `assegnatario` che punta agli utenti (cache per classe)."""
    if modello not in _ha_assegnatario:
        try:
            campo = modello._meta.get_field("assegnatario")
        except Exception:
            campo = None
        _ha_assegnatario[modello] = bool(
            campo is not None and campo.many_to_one
            and campo.related_model._meta.label == settings.AUTH_USER_MODEL)
    return _ha_assegnatario[modello]


def _agente(utente_id):
    if not utente_id:
        return None
    return Agente.objects.filter(utente_id=utente_id).only("nome").first()


def nome_vista(modello):
    """Il nome della vista del modello (quello degli strumenti), o l'etichetta del modello."""
    from core.viste import registry
    v = registry.per_modello(modello)
    return f"{v.modulo}.{v.slug}" if v is not None else modello._meta.label_lower


def _destinazione(instance):
    """(nome, id) del record da segnalare."""
    from core.models import AttivitaPianificata
    if isinstance(instance, AttivitaPianificata):
        modello = instance.content_type.model_class()
        return (nome_vista(modello) if modello is not None else None), instance.object_id
    return nome_vista(type(instance)), instance.pk


def prima_del_salvataggio(sender, instance, raw=False, **kwargs):
    """Ricorda l'assegnatario di prima, ma solo se quello nuovo è un agente (altrimenti nessuna query)."""
    if raw or not _campo_utente(sender):
        return
    try:
        nuovo = getattr(instance, "assegnatario_id", None)
        if not nuovo or not instance.pk or _agente(nuovo) is None:
            return
        instance._awf_assegnatario_prima = (sender._default_manager.filter(pk=instance.pk)
                                            .values_list("assegnatario_id", flat=True).first())
    except Exception:                                   # mai rompere il salvataggio dell'utente
        log.exception("assegnatario precedente non letto")


def dopo_il_salvataggio(sender, instance, created, raw=False, **kwargs):
    if raw or not _campo_utente(sender):
        return
    try:
        nuovo = getattr(instance, "assegnatario_id", None)
        if not created and getattr(instance, "_awf_assegnatario_prima", None) == nuovo:
            return
        agente = _agente(nuovo)
        if agente is None:
            return
        from core import parametri

        from .models import Collegamento
        if not parametri.leggi("awf.eventi") or not Collegamento.attuale().collegato:
            return
        modello, record_id = _destinazione(instance)
        if not modello or not record_id:
            return
        nome = agente.nome
        transaction.on_commit(lambda: _accoda(modello, int(record_id), nome))
    except Exception:                                   # mai rompere il salvataggio dell'utente
        log.exception("evento di assegnazione non preparato")
    finally:
        instance.__dict__.pop("_awf_assegnatario_prima", None)


def _accoda(modello, record_id, agente):
    from core import lavori
    try:
        lavori.accoda("awf.eventi.invia", tipo="record.assigned", modello=modello, record_id=record_id,
                      agente=agente)
    except Exception:
        log.exception("evento di assegnazione non accodato")


def invia(tipo, modello, record_id, agente=None):
    """Lavoro in background: manda l'evento. Un errore va nel lavoro (e nel log) e il worker ritenta."""
    from . import fabbrica
    try:
        risposta = fabbrica.invia_evento(tipo, modello, record_id, agente)
    except (fabbrica.ErroreFabbrica, ValueError) as e:
        log.warning("evento %s su %s non inviato: %s", tipo, modello, e)
        raise
    return f"evento {tipo} accettato (lavoro {risposta.get('job_id') or '—'})"
