"""Prezzo di un prodotto: dal listino (scaglione con la quantità minima più alta raggiunta) o di vendita."""
from decimal import Decimal


def prezzo(prodotto, listino=None, quantita=1):
    if listino is not None:
        voce = (listino.prezzi.filter(prodotto=prodotto, quantita_minima__lte=Decimal(quantita or 1))
                .order_by("-quantita_minima").first())
        if voce is not None:
            return voce.prezzo
    return prodotto.prezzo_vendita
