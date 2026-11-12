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

    from .models import Frammento, IndiceDocumento
    Frammento.objects.filter(fonte=Frammento.DOCUMENTO, content_type=ContentType.objects.get_for_model(sender),
                             object_id=instance.pk).delete()
    IndiceDocumento.objects.filter(documento_id=instance.pk).delete()


def _cambiati(sender, pks, **_):
    _accoda(list(pks))


def _restano_i_costi(sender, instance, **_):
    """Eliminando una chat i suoi turni restano come righe di costo, senza più niente della conversazione (risposta,
    errore, passi, fonti consultate): se sparissero, cancellare le chat azzererebbe il consumo del mese, e con lui le
    quote della licenza, il tetto di spesa e i consumi riferiti al portale."""
    from .models import Turno
    Turno.objects.filter(conversazione=instance).update(testo="", errore="", avanzamento=[], provenienza={})


def collega_costi():
    from django.db.models.signals import pre_delete

    from .models import Conversazione
    pre_delete.connect(_restano_i_costi, sender=Conversazione, dispatch_uid="ai.restano_i_costi")


def collega_documenti():
    from documenti.models import Documento
    from documenti.segnali import documenti_cambiati
    post_save.connect(_salvato, sender=Documento, dispatch_uid="ai.indice.documento_salvato")
    post_delete.connect(_eliminato, sender=Documento, dispatch_uid="ai.indice.documento_eliminato")
    documenti_cambiati.connect(_cambiati, dispatch_uid="ai.indice.documenti_cambiati")


# --- record con un campo lungo indicizzato per sezioni (es. le pagine della wiki) --------------------------------
_A_SEZIONI = None


def _a_sezioni(sender):
    """Il modello ha una vista con `conoscenza_sezioni`? L'elenco si calcola una volta, alla prima occasione: al
    momento dei ready() le viste non sono ancora tutte registrate."""
    global _A_SEZIONI
    if sender.__module__ == "__fake__":                 # modelli storici delle migrazioni
        return False
    if _A_SEZIONI is None:
        from .conoscenza import viste_a_sezioni
        _A_SEZIONI = frozenset(viste_a_sezioni())
    return sender._meta.label_lower in _A_SEZIONI


def _record_cambiato(sender, instance, raw=False, **_):
    if raw or not _a_sezioni(sender):
        return
    from django.contrib.contenttypes.models import ContentType

    from .conoscenza import accoda_record
    ct, pk = ContentType.objects.get_for_model(sender).pk, instance.pk
    transaction.on_commit(lambda: accoda_record(ct, pk))


def collega_sezioni():
    post_save.connect(_record_cambiato, dispatch_uid="ai.indice.record_a_sezioni_salvato")
    post_delete.connect(_record_cambiato, dispatch_uid="ai.indice.record_a_sezioni_eliminato")
