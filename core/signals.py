from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Azienda, ProfiloUtente, Ruolo


def crea_profilo(utente):
    """Profilo con tutte le aziende attive; predefinita la prima per nome."""
    profilo, creato = ProfiloUtente.objects.get_or_create(utente=utente)
    if creato:
        from . import ruoli
        attive = list(Azienda.objects.filter(attiva=True).order_by("nome"))
        profilo.aziende.set(attive)
        profilo.azienda_predefinita = attive[0] if attive else None
        profilo.ruolo = ruoli.predefinito()
        profilo.save(update_fields=["azienda_predefinita", "ruolo"])
    return profilo


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def profilo_al_nuovo_utente(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        crea_profilo(instance)


@receiver(post_save, sender=Azienda)
def sequenze_alla_nuova_azienda(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        from . import sequenze
        sequenze.crea(list(sequenze.definizioni().values()), [instance])


@receiver(post_save, sender=ProfiloUtente)
def gruppi_dal_profilo(sender, instance, raw=False, **kwargs):
    """Ruolo o eccezioni cambiati (da una pagina o dall'admin): i gruppi seguono."""
    if not raw:
        from . import ruoli
        ruoli.applica(instance.utente)


@receiver(post_save, sender=Ruolo)
def gruppi_dal_ruolo(sender, instance, raw=False, **kwargs):
    """Un ruolo cambiato vale subito per tutti quelli che lo hanno."""
    if not raw:
        from . import ruoli
        ruoli.applica_al_ruolo(instance)
