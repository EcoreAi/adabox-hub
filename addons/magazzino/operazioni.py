"""Spedizione delle consegne e ricezione dei ricevimenti: i movimenti di magazzino nascono qui."""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from core import parametri, sequenze

from .models import Consegna, Movimento, Ricevimento, giacenza


def _negativa_ammessa(azienda):
    try:
        return parametri.leggi("magazzino.giacenza_negativa", azienda)
    except KeyError:
        return True


@transaction.atomic
def spedisci(consegna, utente=None):
    """DDT numerato e scarico di ogni riga. Senza giacenze negative ammesse, controlla la disponibilità."""
    if consegna.stato != Consegna.BOZZA:
        raise ValidationError("La consegna non è da spedire.")
    righe = list(consegna.righe.select_related("prodotto"))
    if not righe:
        raise ValidationError("La consegna non ha righe.")
    if not _negativa_ammessa(consegna.azienda):
        mancanti = [f"{r.prodotto} (disponibili {giacenza(r.prodotto, consegna.magazzino)})"
                    for r in righe if giacenza(r.prodotto, consegna.magazzino) < r.quantita]
        if mancanti:
            raise ValidationError("Merce insufficiente: " + ", ".join(mancanti))
    ct = ContentType.objects.get_for_model(Consegna)
    for r in righe:
        Movimento.objects.create(azienda=consegna.azienda, prodotto=r.prodotto, magazzino=consegna.magazzino,
                                 quantita=-Decimal(r.quantita), tipo=Movimento.SCARICO, utente=utente,
                                 causale=f"Consegna a {consegna.cliente}", content_type=ct, object_id=consegna.pk)
    consegna.numero = sequenze.prossimo("magazzino.ddt", consegna.azienda)
    consegna.stato = Consegna.FATTO
    consegna.save(update_fields=["numero", "stato"])


@transaction.atomic
def ricevi(ricevimento, utente=None):
    if ricevimento.stato != Ricevimento.BOZZA:
        raise ValidationError("Il ricevimento non è da ricevere.")
    righe = list(ricevimento.righe.select_related("prodotto"))
    if not righe:
        raise ValidationError("Il ricevimento non ha righe.")
    ct = ContentType.objects.get_for_model(Ricevimento)
    for r in righe:
        Movimento.objects.create(azienda=ricevimento.azienda, prodotto=r.prodotto, magazzino=ricevimento.magazzino,
                                 quantita=Decimal(r.quantita), tipo=Movimento.CARICO, utente=utente,
                                 causale=f"Ricevimento da {ricevimento.fornitore}", content_type=ct,
                                 object_id=ricevimento.pk)
    ricevimento.stato = Ricevimento.FATTO
    ricevimento.save(update_fields=["stato"])
