"""A quale record esterno corrisponde un record di adabox, e viceversa."""
from django.contrib.contenttypes.models import ContentType

from .models import RiferimentoEsterno


def collega(obj, sistema, id_esterno):
    """Un record ha un solo identificativo per sistema: se cambia si aggiorna."""
    rif, _ = RiferimentoEsterno.objects.update_or_create(
        azienda_id=obj.azienda_id, sistema=sistema, content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk,
        defaults={"id_esterno": str(id_esterno)})
    return rif


def id_esterno(obj, sistema):
    return (RiferimentoEsterno.objects.filter(azienda_id=obj.azienda_id, sistema=sistema, content_type=ContentType.objects.get_for_model(obj),
                                              object_id=obj.pk).values_list("id_esterno", flat=True).first())


def trova(modello, azienda, sistema, id_est):
    """Il record di adabox collegato all'identificativo esterno, sempre dentro l'azienda data."""
    pk = (RiferimentoEsterno.objects.filter(azienda=azienda, sistema=sistema, content_type=ContentType.objects.get_for_model(modello),
                                            id_esterno=str(id_est)).values_list("object_id", flat=True).first())
    return modello._default_manager.filter(pk=pk, azienda=azienda).first() if pk else None
