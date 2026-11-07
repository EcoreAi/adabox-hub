"""Spedizione delle consegne e ricezione dei ricevimenti: i movimenti di magazzino nascono qui."""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from core import parametri, sequenze

from . import costi, lotti
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
    piano = [(r, lotti.per_uscita(r, r.prodotto, consegna.magazzino)) for r in righe]      # prima tutti i controlli
    for r, parti in piano:
        for lotto, quantita in parti:
            Movimento.objects.create(azienda=consegna.azienda, prodotto=r.prodotto, magazzino=consegna.magazzino,
                                     ubicazione=r.ubicazione, lotto=lotto, quantita=-quantita, tipo=Movimento.SCARICO,
                                     utente=utente, causale=f"Consegna a {consegna.cliente}", content_type=ct,
                                     object_id=consegna.pk)
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
    dall_ordine = costi_ordine(ricevimento)
    piano = [(r, lotti.per_entrata(r, r.prodotto)) for r in righe]
    for r, parti in piano:
        costo = r.costo if r.costo is not None else dall_ordine.get(r.prodotto_id)
        for lotto, quantita in parti:
            Movimento.objects.create(azienda=ricevimento.azienda, prodotto=r.prodotto, magazzino=ricevimento.magazzino,
                                     ubicazione=r.ubicazione, lotto=lotto, quantita=quantita, tipo=Movimento.CARICO,
                                     utente=utente, causale=f"Ricevimento da {ricevimento.fornitore}", content_type=ct,
                                     object_id=ricevimento.pk, costo_unitario=costo)
    ricevimento.stato = Ricevimento.FATTO
    ricevimento.save(update_fields=["stato"])


def costi_ordine(ricevimento):
    """{prodotto: costo unitario} dalle righe dell'ordine d'acquisto da cui nasce il ricevimento, al netto dello sconto
    (media pesata se il prodotto compare in più righe). Vuoto se il ricevimento non viene da un ordine d'acquisto."""
    ordine = ricevimento.origine
    if ordine is None or not hasattr(ordine, "fornitore") or not hasattr(ordine, "righe"):
        return {}
    somme = {}
    for r in ordine.righe.all():
        if not r.prodotto_id or r.prezzo is None or not r.quantita:
            continue
        netto = Decimal(r.prezzo) * (Decimal(100) - Decimal(getattr(r, "sconto", 0) or 0)) / Decimal(100)
        quantita, valore = somme.get(r.prodotto_id, (Decimal(0), Decimal(0)))
        somme[r.prodotto_id] = (quantita + r.quantita, valore + r.quantita * netto)
    return {pk: costi.q4(valore / quantita) for pk, (quantita, valore) in somme.items() if quantita}



@transaction.atomic
def trasferisci(prodotto, quantita, da_magazzino, a_magazzino, da_ubicazione=None, a_ubicazione=None, utente=None, causale="",
                lotto=None):
    """Sposta merce tra magazzini o ubicazioni: un'uscita e un'entrata di tipo trasferimento, al costo attuale."""
    quantita = Decimal(quantita)
    if quantita <= 0:
        raise ValidationError("La quantità da spostare deve essere positiva.")
    if prodotto.tipo != "bene":
        raise ValidationError("I servizi non si movimentano a magazzino.")
    for magazzino, ubicazione in ((da_magazzino, da_ubicazione), (a_magazzino, a_ubicazione)):
        if magazzino.azienda_id != prodotto.azienda_id or (ubicazione and ubicazione.magazzino_id != magazzino.pk):
            raise ValidationError("Magazzino o ubicazione non validi.")
    from .models import tracciamento
    if tracciamento(prodotto) and lotto is None:
        raise ValidationError(f"{prodotto} si segue per lotto o seriale: indica quale sposti.")
    if lotto is not None and (lotto.prodotto_id != prodotto.pk or (lotto.seriale and quantita != 1)):
        raise ValidationError("Lotto non valido per questo prodotto o quantità.")
    if (da_magazzino.pk, getattr(da_ubicazione, "pk", None)) == (a_magazzino.pk, getattr(a_ubicazione, "pk", None)):
        raise ValidationError("Partenza e arrivo coincidono.")
    disponibile = giacenza(prodotto, da_magazzino, da_ubicazione, lotto)
    if (not _negativa_ammessa(prodotto.azienda) or (lotto and lotto.seriale)) and disponibile < quantita:
        raise ValidationError(f"Merce insufficiente: disponibili {disponibile}.")
    testo = causale or f"Trasferimento {da_ubicazione or da_magazzino} → {a_ubicazione or a_magazzino}"
    comuni = {"azienda": prodotto.azienda, "prodotto": prodotto, "tipo": Movimento.TRASFERIMENTO, "utente": utente,
              "causale": testo[:200], "lotto": lotto}
    uscita = Movimento.objects.create(magazzino=da_magazzino, ubicazione=da_ubicazione, quantita=-quantita, **comuni)
    entrata = Movimento.objects.create(magazzino=a_magazzino, ubicazione=a_ubicazione,
                                       quantita=quantita, **comuni)
    return uscita, entrata
