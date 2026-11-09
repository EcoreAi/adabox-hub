"""Triangolazione: le righe di vendita «spedisce il fornitore» diventano, alla conferma dell'ordine, richieste ai
fornitori con il cliente come destinatario; il magazzino non si muove. Lo spedito si segna sull'ordine al fornitore."""
import logging
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core import chatter

from . import listini
from .models import OrdineAcquisto, RigaAcquisto
from .operazioni import _nuovo_ordine

log = logging.getLogger(__name__)


def _indirizzo(ordine):
    i = getattr(ordine, "indirizzo_consegna", None)
    if i is not None:
        return str(i)
    c = ordine.cliente
    return ", ".join(x for x in (c.indirizzo, f"{c.cap} {c.citta}".strip(), c.provincia, c.nazione if c.nazione != "IT" else "") if x)


def da_vendita(sender, ordine, utente=None, **kwargs):
    """All'ordine di vendita confermato: una richiesta per fornitore con le righe in triangolazione. Non blocca mai la
    conferma: le righe senza fornitore in listino restano da ordinare a mano (nota sull'ordine)."""
    try:
        with transaction.atomic():
            righe = [r for r in ordine.righe.select_related("prodotto") if getattr(r, "diretta", False) and r.prodotto_id]
            if not righe:
                return []
            per_fornitore, senza = defaultdict(list), []
            for r in righe:
                voce, quantita = listini.scegli_fornitore(r.prodotto, r.quantita_base or r.quantita)
                if voce is None:
                    senza.append(r)
                else:
                    per_fornitore[voce.fornitore].append((r, quantita))
            ordini = []
            for fornitore, gruppo in per_fornitore.items():
                oa = _nuovo_ordine(ordine.azienda, fornitore, utente, consegna_a=ordine.cliente, indirizzo_consegna=_indirizzo(ordine),
                                   ordine_vendita_id=ordine.pk,
                                   note=f"Spedire direttamente a {ordine.cliente}: {_indirizzo(ordine)}. Riferimento: {ordine.numero_ordine or ordine.pk}.")
                for r, quantita in gruppo:
                    RigaAcquisto.objects.create(ordine=oa, prodotto=r.prodotto, quantita=quantita, unita=r.prodotto.unita)
                oa.ricalcola()
                ordini.append(oa)
            testo = "Triangolazione: " + (", ".join(f"richiesta {o.numero} a {o.fornitore}" for o in ordini) or "nessuna richiesta")
            if senza:
                testo += ". Senza fornitore in listino, da ordinare a mano: " + ", ".join(str(r.prodotto) for r in senza)
            chatter.scrivi(ordine, utente, testo + ".", tipo="nota")
            return ordini
    except Exception:
        log.exception("triangolazione dell'ordine %s non riuscita", ordine.pk)
        return []


def segna_spedito(ordine, utente=None, data=None):
    if not ordine.consegna_a_id:
        raise ValidationError("Non è un ordine in triangolazione.")
    if ordine.stato != OrdineAcquisto.CONFERMATO:
        raise ValidationError("Prima conferma l'ordine al fornitore.")
    if ordine.spedito_il:
        raise ValidationError(f"Già spedito il {ordine.spedito_il:%d/%m/%Y}.")
    ordine.spedito_il = data or timezone.localdate()
    ordine.save(update_fields=["spedito_il"])
    chatter.scrivi(ordine, utente, f"Il fornitore ha spedito a {ordine.consegna_a} il {ordine.spedito_il:%d/%m/%Y}.", tipo="nota")
    from django.apps import apps
    if ordine.ordine_vendita_id and apps.is_installed("vendite"):
        from vendite.models import OrdineVendita
        ov = OrdineVendita.objects.filter(pk=ordine.ordine_vendita_id).first()
        if ov is not None:
            chatter.scrivi(ov, utente, f"Triangolazione: {ordine.fornitore} ha spedito al cliente ({ordine.numero}).", tipo="nota")
    return ordine
