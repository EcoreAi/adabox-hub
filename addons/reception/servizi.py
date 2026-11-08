"""Entrata e uscita dei visitatori, avviso a chi li riceve, conservazione limitata."""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from core import chatter, parametri

from .models import Visita


def presenti(azienda):
    return Visita.objects.filter(azienda=azienda, entrata__isnull=False, uscita__isnull=True).select_related("ospite").order_by("entrata")


def attese_oggi(azienda):
    oggi = timezone.localdate()
    return Visita.objects.filter(azienda=azienda, entrata__isnull=True, prevista_il__date=oggi).select_related("ospite")


def entra(azienda, nome, societa="", ospite=None, motivo="", email="", telefono="", registrata_da=None):
    """Il visitatore entra: si usa la visita attesa di oggi con lo stesso nome (o email), altrimenti una nuova.
    Chi lo riceve segue la visita e riceve un messaggio: per email e, se c'è Discuss, nella posta in arrivo."""
    nome = " ".join(nome.split())
    attesa = attese_oggi(azienda).filter(Q(nome__iexact=nome) | (Q(email__iexact=email) if email else Q(pk=None))).first()
    v = attesa or Visita(azienda=azienda, nome=nome)
    v.societa = societa or v.societa
    v.ospite = ospite or v.ospite
    v.motivo = motivo or v.motivo
    v.email, v.telefono = email or v.email, telefono or v.telefono
    v.privacy, v.entrata = True, timezone.now()
    v.save()
    if v.ospite_id:
        chatter.segui(v, v.ospite)
        chatter.scrivi(v, registrata_da, f"{v} è arrivato in reception" + (f" per: {v.motivo}" if v.motivo else "") + ".")
    else:
        chatter.scrivi(v, registrata_da, "Entrato in reception.", tipo="sistema")
    return v


def esce(visita, utente=None):
    if visita.uscita is None and visita.entrata is not None:
        visita.uscita = timezone.now()
        visita.save(update_fields=["uscita"])
        chatter.scrivi(visita, utente, "Uscito.", tipo="sistema")
    return visita


def cancella_vecchie():
    """Lavoro pianificato: le visite oltre il tempo di conservazione dell'azienda si cancellano."""
    from core.models import Azienda
    cancellate = 0
    for azienda in Azienda.objects.all():
        giorni = parametri.leggi("reception.giorni_conservazione", azienda) or 365
        limite = timezone.now() - timedelta(days=int(giorni))
        n, _ = Visita.objects.filter(azienda=azienda, creato__lt=limite).filter(Q(uscita__isnull=False) | Q(entrata__isnull=True)).delete()
        cancellate += n
    return cancellate
