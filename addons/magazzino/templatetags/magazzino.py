from django import template

from magazzino import collegamenti
from magazzino.models import Consegna, Ricevimento

register = template.Library()


@register.simple_tag
def consegne_di(ordine):
    return collegamenti.di(ordine, Consegna)


@register.simple_tag
def ricevimenti_di(ordine):
    return collegamenti.di(ordine, Ricevimento)


@register.simple_tag
def costo_prodotto(prodotto):
    """Giacenza, costo e valore attuali del bene, con il metodo in uso e la scelta salvata sul prodotto."""
    from magazzino import costi
    if prodotto.tipo != "bene":
        return None
    stato, _ = costi.ripercorri(prodotto)
    scelta = getattr(prodotto, "metodo_costo", None)
    return {"quantita": stato.quantita, "costo": stato.costo_corrente, "valore": costi.q2(stato.valore),
            "metodo": dict(costi.METODI)[stato.metodo], "scelta": scelta.metodo if scelta else "",
            "metodo_azienda": dict(costi.METODI)[costi.metodo_azienda(prodotto.azienda)]}
