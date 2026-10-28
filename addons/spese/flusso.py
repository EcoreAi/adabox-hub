"""Invio, approvazione, rifiuto e rimborso delle note spese, con avvisi nel chatter."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from core import chatter

from .models import NotaSpese


def gestore(utente):
    return utente.is_superuser or utente.has_perm("spese.vedi_tutte_note")


def puo_decidere(utente, nota):
    return gestore(utente) or utente in nota.dipendente.approvatori()


def controlla(nota):
    errori = []
    righe = list(nota.righe.select_related("categoria"))
    if not righe:
        errori.append("La nota non ha spese.")
    for r in righe:
        if r.categoria.ricevuta_obbligatoria and not r.ricevuta:
            errori.append(f"Manca la ricevuta di «{r}».")
    return errori


def invia(nota, utente):
    if nota.stato not in (NotaSpese.BOZZA, NotaSpese.RIFIUTATA):
        raise ValidationError("La nota è già stata inviata.")
    errori = controlla(nota)
    if errori:
        raise ValidationError(errori)
    nota.ricalcola()
    nota.stato, nota.inviata_il = NotaSpese.INVIATA, timezone.now()
    nota.save(update_fields=["stato", "inviata_il"])
    for u in [nota.dipendente.utente, *nota.dipendente.approvatori()]:
        if u is not None:
            chatter.segui(nota, u)
    chatter.scrivi(nota, utente, f"Nota spese inviata per l'approvazione: {nota.totale} €.", tipo="messaggio")


def decidi(nota, utente, approvata, motivo=""):
    if nota.stato != NotaSpese.INVIATA:
        raise ValidationError("La nota non è da approvare.")
    if not puo_decidere(utente, nota) or (nota.dipendente.utente_id == utente.pk and not utente.is_superuser):
        raise PermissionDenied
    nota.stato = NotaSpese.APPROVATA if approvata else NotaSpese.RIFIUTATA
    nota.decisa_da, nota.nota_decisione = utente, motivo[:250]
    nota.save(update_fields=["stato", "decisa_da", "nota_decisione"])
    chatter.scrivi(nota, utente, ("Nota spese approvata: sarà rimborsata." if approvata else "Nota spese rifiutata.")
                   + (f" {motivo}" if motivo else ""), tipo="messaggio")


def rimborsa(nota, utente, data=None):
    if nota.stato != NotaSpese.APPROVATA:
        raise ValidationError("Si rimborsa solo una nota approvata.")
    if not gestore(utente):
        raise PermissionDenied
    nota.stato, nota.rimborsata_il = NotaSpese.RIMBORSATA, data or timezone.localdate()
    nota.save(update_fields=["stato", "rimborsata_il"])
    chatter.scrivi(nota, utente, f"Rimborsati {nota.totale} € il {nota.rimborsata_il:%d/%m/%Y}.", tipo="messaggio")
