"""Il periodo chiuso dell'azienda: fino alla data di blocco non nascono, non si spostano e non si cancellano documenti
(fatture, incassi, pagamenti, movimenti di magazzino e di cassa…). I moduli dichiarano i loro modelli e il campo data;
un controllo unico sui segnali di salvataggio e cancellazione fa il resto. Gli altri campi (stati, totali) si
aggiornano anche nel periodo chiuso: servono per esempio a segnare pagata una fattura vecchia."""
import datetime

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_delete, pre_save
from django.utils import timezone

_REGISTRO = {}          # "app.Modello" -> (campo data, funzione che dà l'azienda)


def registra(etichetta, campo="data", azienda=None):
    """Da chiamare in AppConfig.ready: `azienda` è una funzione obj -> azienda (di default obj.azienda)."""
    _REGISTRO[etichetta] = (campo, azienda or (lambda obj: getattr(obj, "azienda", None)))
    try:
        modello = apps.get_model(etichetta)
    except LookupError:
        return
    pre_save.connect(_prima_del_salvataggio, sender=modello, dispatch_uid=f"blocco.salva.{etichetta}")
    pre_delete.connect(_prima_della_cancellazione, sender=modello, dispatch_uid=f"blocco.cancella.{etichetta}")


def _giorno(valore):
    if isinstance(valore, datetime.datetime):
        return timezone.localtime(valore).date() if timezone.is_aware(valore) else valore.date()
    return valore


def controlla(azienda, data, cosa="documento"):
    if azienda is None or data is None or not azienda.chiuso_fino_al:
        return
    if _giorno(data) <= azienda.chiuso_fino_al:
        raise ValidationError(f"Il periodo è chiuso fino al {azienda.chiuso_fino_al:%d/%m/%Y}: {cosa} con data {_giorno(data):%d/%m/%Y} "
                              "non si può creare, spostare o cancellare.")


def _azienda_fresca(azienda):
    from .models import Azienda
    return Azienda.objects.filter(pk=azienda.pk).only("pk", "chiuso_fino_al").first() if azienda is not None else None


def _prima_del_salvataggio(sender, instance, raw=False, update_fields=None, **kwargs):
    if raw:
        return
    campo, di = _REGISTRO[sender._meta.label]
    if update_fields is not None and campo not in update_fields:
        return
    azienda = _azienda_fresca(di(instance))
    nuova = getattr(instance, campo, None)
    if instance._state.adding or instance.pk is None:
        controlla(azienda, nuova, str(sender._meta.verbose_name))
        return
    vecchia = sender._default_manager.filter(pk=instance.pk).values_list(campo, flat=True).first()
    if _giorno(vecchia) != _giorno(nuova):
        controlla(azienda, vecchia, str(sender._meta.verbose_name))
        controlla(azienda, nuova, str(sender._meta.verbose_name))


def _prima_della_cancellazione(sender, instance, **kwargs):
    campo, di = _REGISTRO[sender._meta.label]
    controlla(_azienda_fresca(di(instance)), getattr(instance, campo, None), str(sender._meta.verbose_name))


def registrati():
    return dict(_REGISTRO)
