"""Cartelle collegate a un modello: ogni allegato caricato sui suoi record diventa un documento della cartella."""
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import Allegato

from .models import Cartella, Documento


def cartella_per(allegato):
    cartelle = Cartella.objects.filter(modello_id=allegato.content_type_id)
    if allegato.azienda_id:
        cartelle = cartelle.filter(azienda_id=allegato.azienda_id)
    return cartelle.order_by("pk").first()


def documento_da(allegato, cartella):
    if Documento.objects.filter(allegato=allegato).exists():
        return None
    return Documento.objects.create(azienda=cartella.azienda, cartella=cartella, allegato=allegato, nome=allegato.nome,
                                    mime=allegato.mime, dimensione=allegato.dimensione,
                                    proprietario=allegato.caricato_da, content_type_id=allegato.content_type_id,
                                    object_id=allegato.object_id)


@receiver(post_save, sender=Allegato, dispatch_uid="documenti.allegato")
def allegato_caricato(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        cartella = cartella_per(instance)
        if cartella is not None:
            documento_da(instance, cartella)


@receiver(post_save, sender=Cartella, dispatch_uid="documenti.cartella_collegata")
def cartella_collegata(sender, instance, raw=False, **kwargs):
    """Quando una cartella si collega a un modello raccoglie anche gli allegati già caricati."""
    if raw or not instance.modello_id:
        return
    allegati = Allegato.objects.filter(Q(azienda=instance.azienda) | Q(azienda__isnull=True),
                                       content_type_id=instance.modello_id)
    for allegato in allegati:
        documento_da(allegato, instance)
