"""Chatter: messaggi, note, tracciamento delle modifiche e follower di un record qualsiasi."""
import datetime
import re
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.db.models.fields.files import FieldFile
from django.utils import timezone

from core.generici import ct_di
from core.models import Follower, Messaggio

VUOTO = "—"
MENZIONE = re.compile(r"(?<![\w@])@([\w.+-]{2,150})")


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


def scrivi(obj, autore, corpo="", tipo=Messaggio.MESSAGGIO, allegati=(), modifiche=None, message_id="",
           autore_email="", destinatari=()):
    """Aggiunge una voce al chatter. Chi scrive una nota o un messaggio diventa follower;
    un messaggio (non una nota) parte per email ai follower e agli indirizzi esterni `destinatari`
    (core.chatter.email). Chi è menzionato con @username riceve un avviso (core.chatter.email.menzioni)."""
    m = Messaggio.objects.create(content_type=ct_di(obj), object_id=obj.pk, tipo=tipo, autore=autore,
                                 autore_email=autore_email, corpo=corpo, modifiche=modifiche or [],
                                 message_id=message_id,
                                 destinatari=list(destinatari) if tipo == Messaggio.MESSAGGIO else [])
    if allegati:
        m.allegati.set(allegati)
    if autore is not None and tipo in (Messaggio.NOTA, Messaggio.MESSAGGIO):
        segui(obj, autore)
    from . import email
    if tipo == Messaggio.MESSAGGIO:
        email.accoda_notifica(m)
    if tipo in (Messaggio.NOTA, Messaggio.MESSAGGIO):
        email.accoda_menzioni(m)
    return m


def menzionati(corpo):
    """Gli utenti attivi citati con @username."""
    nomi = {n.lower() for n in MENZIONE.findall(corpo or "")}
    if not nomi:
        return []
    return [u for u in get_user_model().objects.filter(is_active=True) if u.username.lower() in nomi]


def puo_vedere(utente, obj):
    """L'utente vede il record dalla sua vista (azienda, regole del queryset e permesso), come se lo aprisse."""
    from core import azienda
    from core.viste import registry
    vista = registry.per_modello(type(obj))
    if vista is None or not utente.is_active:
        return False
    azienda_record = getattr(obj, vista.company_field, None) if vista.company_field else None
    consentite = azienda.consentite(utente)
    if azienda_record is not None and azienda_record not in consentite:
        return False
    richiesta = SimpleNamespace(user=utente, azienda=azienda_record or (consentite[0] if consentite else None))
    return vista.get_queryset(richiesta).filter(pk=obj.pk).exists() and vista.has_view_permission(richiesta, obj)


def fissa(messaggio, fissato=True):
    """Un messaggio o una nota resta in cima al chatter del record (o torna al suo posto)."""
    if messaggio.tipo in (Messaggio.NOTA, Messaggio.MESSAGGIO) and messaggio.fissato != fissato:
        messaggio.fissato = fissato
        messaggio.save(update_fields=["fissato"])
    return messaggio


def fissati_di(obj):
    return messaggi_di(obj).filter(fissato=True)


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
