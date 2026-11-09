"""Prezzo di un prodotto: dal listino (scaglione con la quantità minima più alta raggiunta) o di vendita."""
from decimal import Decimal


def _voce(listino, prodotto, quantita, data):
    from django.db.models import Q
    return (listino.prezzi.filter(prodotto=prodotto, quantita_minima__lte=Decimal(quantita or 1))
            .filter(Q(valido_dal__isnull=True) | Q(valido_dal__lte=data), Q(valido_al__isnull=True) | Q(valido_al__gte=data))
            .order_by("-quantita_minima").first())


def prezzo(prodotto, listino=None, quantita=1, data=None):
    """Il prezzo valido alla data (oggi se manca): le voci fuori dalle loro date non contano. Per una variante senza
    voce propria vale la voce del modello più il sovrapprezzo della variante."""
    from django.utils import timezone
    if listino is not None:
        data = data or timezone.localdate()
        voce = _voce(listino, prodotto, quantita, data)
        if voce is not None:
            return voce.prezzo
        if prodotto.variante_di_id:
            voce = _voce(listino, prodotto.variante_di, quantita, data)
            if voce is not None:
                from .varianti import sovrapprezzo
                return voce.prezzo + sovrapprezzo(prodotto)
    return prodotto.prezzo_vendita
