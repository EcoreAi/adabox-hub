"""Richiesta, approvazione e rifiuto delle assenze, con avvisi nel chatter (e in Discuss, se c'è)."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from core import chatter

from . import saldi
from .models import Assenza


def gestore(utente):
    return utente.is_superuser or utente.has_perm("personale.vedi_tutte_assenze")


def puo_decidere(utente, assenza):
    return gestore(utente) or utente in assenza.dipendente.approvatori()


def richiesta_inviata(assenza, utente):
    """Il dipendente e chi approva seguono la richiesta; chi approva riceve un messaggio."""
    for u in [assenza.dipendente.utente, *assenza.dipendente.approvatori()]:
        if u is not None:
            chatter.segui(assenza, u)
    avviso = ""
    if assenza.tipo.saldo:
        residuo = saldi.saldo(assenza.dipendente, assenza.dal.year)[assenza.tipo.saldo]
        avviso = f" Residuo dopo la richiesta: {residuo['residue']} {residuo['unita']}."
        if residuo["residue"] < 0:
            avviso += " Attenzione: il saldo va in negativo."
    chatter.scrivi(assenza, utente, f"Nuova richiesta: {assenza}.{avviso}", tipo="messaggio")


def decidi(assenza, utente, approvata, nota=""):
    if assenza.stato != Assenza.RICHIESTA:
        raise ValidationError("La richiesta è già stata decisa.")
    if not puo_decidere(utente, assenza):
        raise PermissionDenied
    assenza.stato = Assenza.APPROVATA if approvata else Assenza.RIFIUTATA
    assenza.decisa_da, assenza.decisa_il, assenza.nota_decisione = utente, timezone.now(), nota[:250]
    assenza.save(update_fields=["stato", "decisa_da", "decisa_il", "nota_decisione"])
    esito = "approvata" if approvata else "rifiutata"
    chatter.scrivi(assenza, utente, f"Richiesta {esito}." + (f" {nota}" if nota else ""), tipo="messaggio")


def annulla(assenza, utente):
    proprietario = assenza.dipendente.utente_id == utente.pk
    if not (proprietario or gestore(utente)):
        raise PermissionDenied
    if assenza.stato == Assenza.APPROVATA and assenza.dal <= timezone.localdate() and not gestore(utente):
        raise ValidationError("Un'assenza già iniziata la annulla solo l'ufficio del personale.")
    assenza.stato = Assenza.ANNULLATA
    assenza.save(update_fields=["stato"])
    chatter.scrivi(assenza, utente, "Richiesta annullata.", tipo="messaggio")
