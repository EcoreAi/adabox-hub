"""Richieste di documenti: un'attività pianificata per il destinatario, chiusa dal caricamento."""
from django.db import transaction

from core import attivita, chatter
from core.generici import ct_di
from core.models import AttivitaPianificata, TipoAttivita

from . import servizi
from .models import Richiesta


def apri(richiesta, utente):
    tipo, _ = TipoAttivita.objects.get_or_create(nome="Da fare", defaults={"icona": "check"})
    attivita.pianifica(richiesta, tipo, richiesta.destinatario, richiesta.scadenza,
                       riepilogo=f"Carica il documento: {richiesta.titolo}"[:200], nota=richiesta.descrizione,
                       creato_da=utente)
    chatter.segui(richiesta, richiesta.destinatario)


def _chiudi_attivita(richiesta):
    AttivitaPianificata.objects.filter(content_type=ct_di(richiesta), object_id=richiesta.pk).delete()


@transaction.atomic
def evadi(richiesta, file, utente):
    """Il documento richiesto va nella cartella indicata (anche se chi carica non ci scrive di solito)."""
    documento = servizi.carica(richiesta.cartella, file, utente, descrizione=f"Richiesto: {richiesta.titolo}")
    richiesta.documento, richiesta.stato = documento, Richiesta.COMPLETATA
    richiesta.save(update_fields=["documento", "stato"])
    _chiudi_attivita(richiesta)
    chatter.scrivi(richiesta, utente, f"Documento caricato: {documento.nome}.", tipo="nota")
    return documento


def annulla(richiesta, utente):
    richiesta.stato = Richiesta.ANNULLATA
    richiesta.save(update_fields=["stato"])
    _chiudi_attivita(richiesta)
    chatter.scrivi(richiesta, utente, "Richiesta annullata.", tipo="sistema")
