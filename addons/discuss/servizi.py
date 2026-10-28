"""Canali, iscrizioni, messaggi e non letti."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, OuterRef, Subquery
from django.utils import timezone

from core import allegati

from .models import Canale, Iscrizione, Messaggio

PAGINA = 50


def puo_vedere(utente, canale):
    if not utente.has_perm("discuss.view_canale"):
        return False
    return canale.tipo == Canale.PUBBLICO or canale.iscrizioni.filter(utente=utente).exists()


def iscrizione(utente, canale):
    return Iscrizione.objects.filter(utente=utente, canale=canale).first()


def iscrivi(canale, utente, ultimo_letto=None):
    if ultimo_letto is None:                       # chi entra non trova lo storico come "non letto"
        ultimo_letto = canale.messaggi.order_by("-pk").values_list("pk", flat=True).first() or 0
    return Iscrizione.objects.get_or_create(canale=canale, utente=utente, defaults={"ultimo_letto": ultimo_letto})[0]


def esci(canale, utente):
    Iscrizione.objects.filter(canale=canale, utente=utente).delete()


@transaction.atomic
def crea_canale(nome, tipo, creato_da, membri=(), descrizione=""):
    canale = Canale.objects.create(nome=nome.strip()[:80], tipo=tipo, creato_da=creato_da, descrizione=descrizione[:250])
    for u in {creato_da, *membri}:
        iscrivi(canale, u, 0)
    return canale


@transaction.atomic
def diretto(utenti):
    """La conversazione diretta tra esattamente queste persone (creata la prima volta)."""
    pk = sorted({u.pk for u in utenti})
    candidati = (Canale.objects.filter(tipo=Canale.DIRETTO).annotate(n=Count("iscrizioni"))
                 .filter(n=len(pk)))
    for c in candidati.filter(iscrizioni__utente_id=pk[0]):
        if sorted(c.iscrizioni.values_list("utente_id", flat=True)) == pk:
            return c
    canale = Canale.objects.create(tipo=Canale.DIRETTO, creato_da=utenti[0])
    for u in get_user_model().objects.filter(pk__in=pk):
        iscrivi(canale, u, 0)
    return canale


@transaction.atomic
def invia(canale, autore, corpo, file=()):
    corpo = (corpo or "").strip()[:10000]
    if not corpo and not file:
        raise ValueError("Il messaggio è vuoto.")
    messaggio = Messaggio.objects.create(canale=canale, autore=autore, corpo=corpo)
    for f in file:
        allegati.salva(messaggio, f, autore)
    Iscrizione.objects.filter(canale=canale, utente=autore).update(ultimo_letto=messaggio.pk)
    from . import notifiche
    notifiche.da_messaggio(messaggio)
    return messaggio


def modifica(messaggio, corpo):
    messaggio.corpo, messaggio.modificato_il = corpo.strip()[:10000], timezone.now()
    messaggio.save(update_fields=["corpo", "modificato_il"])


def elimina(messaggio):
    messaggio.corpo, messaggio.eliminato = "", True
    messaggio.save(update_fields=["corpo", "eliminato"])
    allegati.di(messaggio).delete()


def segna_letto(utente, canale, fino_a):
    Iscrizione.objects.filter(utente=utente, canale=canale, ultimo_letto__lt=fino_a).update(ultimo_letto=fino_a)


def iscrizioni_di(utente):
    """Le conversazioni dell'utente con il numero di messaggi non letti (degli altri), le più recenti prima."""
    non_letti = (Messaggio.objects.filter(canale=OuterRef("canale"), pk__gt=OuterRef("ultimo_letto"), eliminato=False)
                 .exclude(autore=utente).order_by().values("canale").annotate(n=Count("pk")).values("n"))
    ultimo = Messaggio.objects.filter(canale=OuterRef("canale")).order_by("-pk").values("pk")[:1]
    return (Iscrizione.objects.filter(utente=utente, canale__archiviato=False)
            .select_related("canale").prefetch_related("canale__membri")
            .annotate(non_letti=Subquery(non_letti), ultimo=Subquery(ultimo))
            .order_by(F("ultimo").desc(nulls_last=True), "canale__nome"))


def totale_non_letti(utente):
    return sum(i.non_letti or 0 for i in iscrizioni_di(utente))


def messaggi(canale, dopo=None, prima=None):
    qs = canale.messaggi.select_related("autore")
    if dopo is not None:
        return list(qs.filter(pk__gt=dopo)[:200])
    if prima is not None:
        qs = qs.filter(pk__lt=prima)
    return list(reversed(qs.order_by("-pk")[:PAGINA]))


def pubblici_da_scoprire(utente):
    return Canale.objects.filter(tipo=Canale.PUBBLICO, archiviato=False).exclude(iscrizioni__utente=utente)


