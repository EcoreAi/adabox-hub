"""Un collaudo nuovo parte con tutti i casi attivi del progetto."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Collaudo


@receiver(post_save, sender=Collaudo, dispatch_uid="qualita.collaudo_nuovo")
def collaudo_nuovo(sender, instance, created, raw=False, **_):
    if created and not raw:
        instance.aggiungi_casi()
