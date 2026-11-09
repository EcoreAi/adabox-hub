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


@register.simple_tag
def contenuto_ubicazione(ubicazione):
    from magazzino.pagine import contenuto
    return contenuto(ubicazione.magazzino, ubicazione)


@register.simple_tag
def tracciabilita(lotto):
    """Saldo per magazzino e movimenti del lotto con il documento: a monte i ricevimenti, a valle le consegne."""
    from django.db.models import Sum

    from magazzino.models import Movimento
    movimenti = list(Movimento.objects.filter(lotto=lotto).select_related("magazzino", "ubicazione", "content_type").order_by("data", "pk"))
    for m in movimenti:
        documento = m.documento
        m.chi = getattr(documento, "fornitore", None) or getattr(documento, "cliente", None)
        m.doc = documento
    saldi = (Movimento.objects.filter(lotto=lotto).values("magazzino__nome").annotate(t=Sum("quantita")).exclude(t=0))
    return {"movimenti": movimenti, "saldi": list(saldi),
            "fornitori": sorted({str(m.chi) for m in movimenti if m.quantita > 0 and m.chi}),
            "clienti": sorted({str(m.chi) for m in movimenti if m.quantita < 0 and m.chi and m.tipo == "scarico"})}


@register.simple_tag
def tracciamento_prodotto(prodotto):
    t = getattr(prodotto, "tracciamento", None)
    return {"tipo": t.tipo if t else "", "scadenza": t.scadenza if t else False}


@register.simple_tag
def kit_prodotto(prodotto):
    """Per la scheda di un kit: quanti se ne possono fare e la giacenza di ogni componente."""
    from magazzino.models import giacenza
    from magazzino.operazioni import disponibili_kit
    if not prodotto.kit:
        return None
    componenti = [{"c": c, "giacenza": giacenza(c.componente)} for c in prodotto.componenti.select_related("componente")]
    return {"disponibili": disponibili_kit(prodotto), "componenti": componenti}


@register.simple_tag
def ripartizione_costo(costo):
    from decimal import Decimal

    from django.core.exceptions import ValidationError

    from magazzino import accessori
    if costo.stato == costo.APPLICATO:
        righe = [(r.movimento, None, r.quota) for r in costo.ripartizioni.select_related("movimento__prodotto")]
    else:
        try:
            righe = accessori.anteprima(costo)
        except ValidationError:
            return []
    return [{"prodotto": m.prodotto, "quantita": m.quantita, "quota": q, "unita": q / Decimal(m.quantita)} for m, _, q in righe]
