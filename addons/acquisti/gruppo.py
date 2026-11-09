"""Operazioni tra aziende del gruppo (stessa installazione). Alla conferma di un ordine di vendita il cui cliente ha
la partita IVA (o il codice fiscale) di un'altra azienda con una regola attiva, in quell'azienda nasce l'ordine al
fornitore speculare: fornitore ritrovato o creato dalla partita IVA della venditrice, prodotti per codice, stessi
prezzi e aliquote. Il numero dell'ordine al fornitore diventa il riferimento del cliente sull'ordine di vendita, così
la fattura, che lo porta in DatiOrdineAcquisto, all'arrivo dallo SDI si collega da sola all'ordine speculare.
L'annullamento della vendita annulla l'ordine speculare, se si può."""
import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from core import chatter
from core.models import Azienda

from .models import OrdineAcquisto, RegolaGruppo, RigaAcquisto

log = logging.getLogger(__name__)


def _azienda_del_cliente(cliente):
    filtri = Q()
    if cliente.partita_iva:
        filtri |= Q(partita_iva=cliente.partita_iva)
    if cliente.codice_fiscale:
        filtri |= Q(codice_fiscale=cliente.codice_fiscale)
    return Azienda.objects.filter(filtri).first() if filtri else None


def regola_per(ordine):
    acquirente = _azienda_del_cliente(ordine.cliente)
    if acquirente is None or acquirente.pk == ordine.azienda_id:
        return None
    return RegolaGruppo.objects.filter(venditrice_id=ordine.azienda_id, acquirente=acquirente, attiva=True).select_related("acquirente").first()


def _fornitore(acquirente, venditrice):
    from contatti.models import Contatto
    tutti = Contatto.objects.filter(azienda=acquirente)
    trovato = None
    if venditrice.partita_iva:
        trovato = tutti.filter(partita_iva=venditrice.partita_iva).order_by("-fornitore", "pk").first()
    if trovato is None and venditrice.codice_fiscale:
        trovato = tutti.filter(codice_fiscale=venditrice.codice_fiscale).order_by("-fornitore", "pk").first()
    if trovato is None:
        trovato = Contatto.objects.create(azienda=acquirente, nome=venditrice.nome,
                                          partita_iva=venditrice.partita_iva, codice_fiscale=venditrice.codice_fiscale,
                                          fornitore=True)
    elif not trovato.fornitore:
        trovato.fornitore = True
        trovato.save(update_fields=["fornitore"])
    return trovato


def _prodotto(acquirente, prodotto):
    if prodotto is None:
        return None
    from prodotti.models import Prodotto
    return Prodotto.objects.filter(azienda=acquirente, codice=prodotto.codice).first() if prodotto.codice else None


def da_vendita(sender, ordine, utente=None, **kwargs):
    """Ricevitore di ordine_confermato. Non blocca mai la conferma: in caso di problemi lascia una nota."""
    try:
        regola = regola_per(ordine)
        if regola is None or OrdineAcquisto.objects.filter(ordine_gruppo_id=ordine.pk).exists():
            return None
        with transaction.atomic():
            oa = crea_speculare(ordine, regola, utente)
        chatter.scrivi(ordine, None, f"Ordine al fornitore {oa.numero} creato in {regola.acquirente}.", tipo="sistema")
        return oa
    except Exception as e:                                    # noqa: BLE001
        log.exception("Ordine speculare per %s non riuscito", ordine.pk)
        chatter.scrivi(ordine, None, f"Ordine speculare nell'azienda del gruppo non creato: {e}", tipo="nota")
        return None


def crea_speculare(ordine, regola, utente=None):
    from . import operazioni
    acquirente = regola.acquirente
    fornitore = _fornitore(acquirente, ordine.azienda)
    oa = operazioni._nuovo_ordine(acquirente, fornitore, regola.buyer, data=ordine.confermato_il or ordine.data,
                                  riferimento_fornitore=(ordine.numero_ordine or ordine.numero or "")[:100],
                                  ordine_gruppo_id=ordine.pk,
                                  note=f"Ordine speculare dell'ordine {ordine.numero_ordine or ordine.numero} di {ordine.azienda}.")
    for r in ordine.righe.select_related("prodotto", "aliquota").order_by("pk"):
        if getattr(r, "opzionale", False) and not getattr(r, "scelta", False):
            continue
        RigaAcquisto.objects.create(ordine=oa, prodotto=_prodotto(acquirente, r.prodotto), descrizione=r.descrizione or str(r.prodotto or ""),
                                    quantita=r.quantita, prezzo=r.prezzo, sconto=r.sconto, aliquota=r.aliquota)
    oa.ricalcola()
    if not ordine.riferimento_cliente:
        type(ordine).objects.filter(pk=ordine.pk).update(riferimento_cliente=oa.numero)
        ordine.riferimento_cliente = oa.numero
    if regola.conferma:
        try:
            operazioni.conferma(oa, regola.buyer)
        except ValidationError as e:
            chatter.scrivi(oa, None, f"Non confermato da solo: {' '.join(e.messages)}", tipo="nota")
    chatter.scrivi(oa, None, f"Nato dall'ordine di vendita {ordine.numero_ordine or ordine.numero} di {ordine.azienda}.", tipo="sistema")
    return oa


def da_annullamento(sender, ordine, utente=None, **kwargs):
    from . import operazioni
    for oa in OrdineAcquisto.objects.filter(ordine_gruppo_id=ordine.pk).exclude(stato=OrdineAcquisto.ANNULLATO):
        try:
            with transaction.atomic():
                operazioni.annulla(oa, None)
            chatter.scrivi(oa, None, f"Annullato con l'ordine di vendita di {ordine.azienda}.", tipo="sistema")
        except ValidationError as e:
            chatter.scrivi(oa, None, f"La vendita di {ordine.azienda} è annullata, ma l'ordine resta: {' '.join(e.messages)}", tipo="nota")
