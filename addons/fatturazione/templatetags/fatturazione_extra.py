from django import template

from fatturazione.operazioni import fatture_attive

register = template.Library()


@register.simple_tag
def ordine_fatturabile(ordine):
    return ordine.stato == "confermato" and not fatture_attive(ordine)


@register.simple_tag
def credito_cliente(fattura):
    """Il credito del cliente ancora da usare (acconti, eccedenze), se la fattura ha qualcosa da incassare."""
    from fatturazione import operazioni
    from fatturazione.models import Fattura
    if fattura.stato != Fattura.EMESSA or fattura.tipo == Fattura.NOTA_CREDITO or not fattura.cliente_id:
        return 0
    return sum((c.residuo for c in operazioni.crediti_disponibili(fattura.cliente, fattura.azienda)), 0)
