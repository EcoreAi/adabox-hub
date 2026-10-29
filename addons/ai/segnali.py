"""L'assistente segue i Documenti (se installati): ogni documento caricato, salvato, spostato, rinominato o cestinato
torna nell'indice della conoscenza in pochi secondi, con un lavoro in background dopo il salvataggio."""
from django.db import transaction
from django.db.models.signals import post_delete, post_save


def _accoda(pks):
    from .conoscenza import accoda_documento

    def dopo():
        for pk in pks:
            accoda_documento(pk)
    transaction.on_commit(dopo)


def _salvato(sender, instance, raw=False, **_):
    if not raw:                                              # non durante il caricamento dei dati (fixture)
        _accoda([instance.pk])


def _eliminato(sender, instance, **_):
    from django.contrib.contenttypes.models import ContentType

    from .models import Frammento
    Frammento.objects.filter(fonte=Frammento.DOCUMENTO, content_type=ContentType.objects.get_for_model(sender),
                             object_id=instance.pk).delete()


def _cambiati(sender, pks, **_):
    _accoda(list(pks))


def collega_documenti():
    from documenti.models import Documento
    from documenti.segnali import documenti_cambiati
    post_save.connect(_salvato, sender=Documento, dispatch_uid="ai.indice.documento_salvato")
    post_delete.connect(_eliminato, sender=Documento, dispatch_uid="ai.indice.documento_eliminato")
    documenti_cambiati.connect(_cambiati, dispatch_uid="ai.indice.documenti_cambiati")
