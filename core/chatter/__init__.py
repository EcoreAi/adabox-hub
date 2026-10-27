"""Chatter: messaggi, note, tracciamento delle modifiche e follower di un record qualsiasi."""
import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.db.models.fields.files import FieldFile
from django.utils import timezone

from core.generici import ct_di
from core.models import Follower, Messaggio

VUOTO = "—"


def messaggi_di(obj):
    return (Messaggio.objects.filter(content_type=ct_di(obj), object_id=obj.pk)
            .select_related("autore").prefetch_related("allegati"))


def testo_campo(obj, campo):
    """Valore di un campo come testo semplice (per il tracciamento e le email)."""
    f = obj._meta.get_field(campo)
    if f.many_to_many:
        return ", ".join(sorted(str(v) for v in getattr(obj, campo).all())) or VUOTO
    if f.choices:
        return getattr(obj, f"get_{campo}_display")() or VUOTO
    valore = getattr(obj, campo)
    if isinstance(valore, FieldFile):
        valore = valore.name
    if valore is None or valore == "":
        return VUOTO
    if isinstance(valore, bool):
        return "Sì" if valore else "No"
    if isinstance(valore, datetime.datetime):
        return timezone.localtime(valore).strftime("%d/%m/%Y %H:%M") if timezone.is_aware(valore) \
            else valore.strftime("%d/%m/%Y %H:%M")
    if isinstance(valore, datetime.date):
        return valore.strftime("%d/%m/%Y")
    return str(valore)


def valori(obj, campi):
    return {c: testo_campo(obj, c) for c in campi}


def _etichetta(obj, campo):
    try:
        nome = str(obj._meta.get_field(campo).verbose_name)
    except FieldDoesNotExist:
        nome = campo
    return nome[:1].upper() + nome[1:]


def scrivi(obj, autore, corpo="", tipo=Messaggio.MESSAGGIO, allegati=(), modifiche=None, message_id=""):
    """Aggiunge una voce al chatter. Chi scrive una nota o un messaggio diventa follower;
    un messaggio (non una nota) parte per email ai follower (core.chatter.email)."""
    m = Messaggio.objects.create(content_type=ct_di(obj), object_id=obj.pk, tipo=tipo, autore=autore,
                                 corpo=corpo, modifiche=modifiche or [], message_id=message_id)
    if allegati:
        m.allegati.set(allegati)
    if autore is not None and tipo in (Messaggio.NOTA, Messaggio.MESSAGGIO):
        segui(obj, autore)
    if tipo == Messaggio.MESSAGGIO:
        from . import email
        email.accoda_notifica(m)
    return m


def traccia(obj, vecchi, autore=None):
    """Confronta i valori `vecchi` ({campo: testo}) con quelli attuali; se cambiano, una voce di tracciamento."""
    modifiche = []
    for campo, prima in vecchi.items():
        dopo = testo_campo(obj, campo)
        if dopo != prima:
            modifiche.append({"campo": campo, "label": _etichetta(obj, campo), "prima": prima, "dopo": dopo})
    if modifiche:
        return scrivi(obj, autore, tipo=Messaggio.TRACCIAMENTO, modifiche=modifiche)
    return None


def segui(obj, utente):
    Follower.objects.get_or_create(content_type=ct_di(obj), object_id=obj.pk, utente=utente)


def smetti(obj, utente):
    Follower.objects.filter(content_type=ct_di(obj), object_id=obj.pk, utente=utente).delete()


def follower_di(obj):
    return get_user_model().objects.filter(
        segue__content_type=ct_di(obj), segue__object_id=obj.pk).order_by("first_name", "username")


def segue(obj, utente):
    return Follower.objects.filter(content_type=ct_di(obj), object_id=obj.pk, utente=utente).exists()
