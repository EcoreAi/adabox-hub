from django import template

register = template.Library()


@register.simple_tag
def pagamento_fattura(fattura):
    """Per la scheda della fattura: il link «Paga ora» da mandare al cliente e i pagamenti online già tentati."""
    from pagamenti import servizi
    return {"pagabile": servizi.pagabile(fattura), "link": servizi.link(fattura) if servizi.pagabile(fattura) else "",
            "pagamenti": list(fattura.pagamenti_online.all()[:10])}


@register.simple_tag
def pagabile_online(fattura):
    from pagamenti import servizi
    return servizi.pagabile(fattura)
