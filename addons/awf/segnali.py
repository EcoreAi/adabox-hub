"""Collegamento dei segnali di AWF (importato da `AwfConfig.ready`)."""
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_delete, post_save, pre_save

from core.models import TokenApi

from . import agenti, eventi
from .models import OperazioneAmmessa

# gli utenti agente non entrano nell'interfaccia e non hanno token API
user_logged_in.connect(agenti.accesso_negato, dispatch_uid="awf.accesso_negato")
pre_save.connect(agenti.token_negato, sender=TokenApi, dispatch_uid="awf.token_negato")

# assegnazioni agli agenti → evento alla fabbrica (solo per i modelli con un campo assegnatario)
pre_save.connect(eventi.prima_del_salvataggio, dispatch_uid="awf.eventi.prima")
post_save.connect(eventi.dopo_il_salvataggio, dispatch_uid="awf.eventi.dopo")


def _operazioni_cambiate(sender, instance=None, raw=False, **kwargs):
    if raw:
        return
    from . import operazioni
    operazioni.allinea_gruppo()


# i permessi degli agenti seguono l'elenco delle operazioni ammesse
post_save.connect(_operazioni_cambiate, sender=OperazioneAmmessa, dispatch_uid="awf.operazioni.salvata")
post_delete.connect(_operazioni_cambiate, sender=OperazioneAmmessa, dispatch_uid="awf.operazioni.eliminata")
