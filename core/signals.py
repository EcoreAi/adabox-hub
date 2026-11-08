from django.conf import settings
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete
from django.dispatch import receiver

from .models import Azienda, Dipartimento, ProfiloUtente, Ruolo


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


@receiver(post_save, sender=Dipartimento)
def gruppi_dal_dipartimento(sender, instance, raw=False, **kwargs):
    """App del dipartimento cambiate: valgono subito per chi ne fa parte."""
    if not raw:
        from . import dipartimenti
        dipartimenti.riapplica(instance.profili.values_list("utente_id", flat=True))


@receiver(pre_delete, sender=Dipartimento)
def membri_prima_di_eliminare(sender, instance, **kwargs):
    instance._membri = list(instance.profili.values_list("utente_id", flat=True))


@receiver(post_delete, sender=Dipartimento)
def gruppi_dopo_eliminazione(sender, instance, **kwargs):
    from . import dipartimenti
    dipartimenti.riapplica(getattr(instance, "_membri", []))


@receiver(m2m_changed, sender=ProfiloUtente.dipartimenti.through)
def gruppi_dai_membri(sender, instance, action, reverse, pk_set, **kwargs):
    """Persona aggiunta o tolta da un dipartimento, da una parte o dall'altra della relazione."""
    if action not in ("post_add", "post_remove", "post_clear", "pre_clear"):
        return
    from . import dipartimenti
    if not reverse:                                          # profilo.dipartimenti.add(...)
        if action != "pre_clear":
            dipartimenti.riapplica([instance.utente_id])
        return
    if action == "pre_clear":                                # dipartimento.profili.clear(): chi c'era
        instance._membri_prima = list(instance.profili.values_list("utente_id", flat=True))
        return
    if action == "post_clear":
        utenti = getattr(instance, "_membri_prima", [])
    else:
        utenti = ProfiloUtente.objects.filter(pk__in=pk_set or []).values_list("utente_id", flat=True)
    dipartimenti.riapplica(utenti)
