"""Da dove viene il prezzo di una riga: contratto quadro, poi listino del fornitore. Il costo del prodotto è il ripiego."""
from django.db.models import Q
from django.utils import timezone

from .models import CondizioniFornitore, ContrattoQuadro, RigaContratto, VoceListino


def validi(azienda, data=None):
    data = data or timezone.localdate()
    return VoceListino.objects.filter(azienda=azienda).filter(
        Q(valido_dal__isnull=True) | Q(valido_dal__lte=data), Q(valido_al__isnull=True) | Q(valido_al__gte=data))


def voce(fornitore, prodotto, quantita, data=None):
    """Lo scaglione che si applica alla quantità: quello col minimo più alto ancora raggiunto."""
    return (validi(fornitore.azienda, data).filter(fornitore=fornitore, prodotto=prodotto, quantita_minima__lte=quantita)
            .order_by("-quantita_minima", "prezzo", "pk").first())


def minimo(fornitore, prodotto, data=None):
    return (validi(fornitore.azienda, data).filter(fornitore=fornitore, prodotto=prodotto)
            .order_by("quantita_minima").values_list("quantita_minima", flat=True).first())


def scegli_fornitore(prodotto, quantita, data=None):
    """(voce, quantità da ordinare) del fornitore da proporre: prima il preferito, poi il prezzo più basso.
    La quantità sale al minimo d'ordine del fornitore, se serve. (None, quantità) senza listino."""
    per_fornitore = {}
    for v in validi(prodotto.azienda, data).filter(prodotto=prodotto).order_by("quantita_minima"):
        per_fornitore.setdefault(v.fornitore_id, []).append(v)
    candidati = []
    for voci in per_fornitore.values():
        da_ordinare = max(quantita, voci[0].quantita_minima)
        scaglione = [v for v in voci if v.quantita_minima <= da_ordinare][-1]
        preferito = any(v.preferito for v in voci)
        candidati.append((not preferito, scaglione.prezzo * da_ordinare, scaglione.pk, scaglione, da_ordinare))
    if not candidati:
        return None, quantita
    _, _, _, scaglione, da_ordinare = min(candidati, key=lambda c: c[:3])
    return scaglione, da_ordinare


def prezzo_contratto(ordine, prodotto):
    if not ordine.contratto_id:
        return None
    riga = RigaContratto.objects.filter(contratto_id=ordine.contratto_id, prodotto=prodotto).first()
    return riga.prezzo if riga else None


def condizioni(fornitore):
    return CondizioniFornitore.objects.filter(fornitore=fornitore).select_related("aliquota", "termine_pagamento").first()


def contratti_attivi(fornitore, data=None):
    data = data or timezone.localdate()
    return ContrattoQuadro.objects.filter(fornitore=fornitore, stato=ContrattoQuadro.ATTIVO, dal__lte=data).filter(
        Q(al__isnull=True) | Q(al__gte=data))
