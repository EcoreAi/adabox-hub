"""Da un record salvato o eliminato a una consegna per ogni webhook che lo ascolta. Solo i modelli con una vista per
azienda aperta all'API: ciò che non è esposto all'API non esce nemmeno da qui."""
import threading
from contextlib import contextmanager

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from core import lavori
from core.viste import registry

from .models import ConsegnaWebhook, Webhook

_locale = threading.local()


@contextmanager
def senza_eventi():
    """Per i connettori: ciò che arriva dall'esterno non si rimanda all'esterno, altrimenti i due sistemi si rincorrono."""
    prima = getattr(_locale, "muto", False)
    _locale.muto = True
    try:
        yield
    finally:
        _locale.muto = prima


def nome_evento(modello, azione):
    return f"{modello._meta.label_lower}.{azione}"


def _vista(sender):
    vista = registry.per_modello(sender)
    return vista if vista is not None and vista.api and vista.company_field else None


def _accoda(consegna):
    lavori.accoda("connettori.consegne.invia", consegna_id=consegna.pk, azienda=consegna.azienda, max_tentativi=5)


def _crea(webhook, evento, ct, pk, istantanea=None):
    if istantanea is None and ConsegnaWebhook.objects.filter(webhook=webhook, evento=evento, content_type=ct, object_id=pk,
                                                             stato=ConsegnaWebhook.IN_CODA, tentativi=0).exists():
        return None                                     # ne parte già una: leggerà il record aggiornato
    consegna = ConsegnaWebhook.objects.create(webhook=webhook, azienda=webhook.azienda, evento=evento, content_type=ct,
                                              object_id=pk, istantanea=istantanea)
    _accoda(consegna)
    return consegna


def _pubblica(azienda_id, evento, ct, pk, istantanea=None):
    for webhook in Webhook.objects.filter(azienda_id=azienda_id, attivo=True).select_related("azienda"):
        if webhook.ascolta(evento):
            _crea(webhook, evento, ct, pk, istantanea)


def salvato(sender, instance, created=False, raw=False, **_):
    if raw or getattr(_locale, "muto", False) or (vista := _vista(sender)) is None:
        return
    azienda_id = getattr(instance, f"{vista.company_field}_id", None)
    if azienda_id is None or not Webhook.objects.filter(azienda_id=azienda_id, attivo=True).exists():
        return
    evento, pk, ct = nome_evento(sender, "creato" if created else "aggiornato"), instance.pk, ContentType.objects.get_for_model(sender)
    transaction.on_commit(lambda: _pubblica(azienda_id, evento, ct, pk))


def eliminato(sender, instance, **_):
    """Dopo l'eliminazione il record non c'è più: i suoi dati si fissano adesso."""
    if getattr(_locale, "muto", False) or (vista := _vista(sender)) is None:
        return
    azienda_id = getattr(instance, f"{vista.company_field}_id", None)
    if azienda_id is None or not Webhook.objects.filter(azienda_id=azienda_id, attivo=True).exists():
        return
    evento, pk, ct = nome_evento(sender, "eliminato"), instance.pk, ContentType.objects.get_for_model(sender)
    transaction.on_commit(lambda: _pubblica(azienda_id, evento, ct, pk, {"id": pk}))


def prova(webhook):
    """Una consegna di prova, anche se il webhook non ascolta nulla di simile."""
    return _crea(webhook, "connettori.prova", None, None, {"messaggio": "Prova da adabox"})
