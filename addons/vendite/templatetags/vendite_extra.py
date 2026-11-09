from django import template

register = template.Library()


@register.simple_tag
def condizioni_cliente(contatto):
    """Per la scheda del contatto cliente: listino e sconto, le regole di sconto che lo riguardano."""
    from prodotti.models import Listino
    from vendite.models import CondizioniCliente, RegolaSconto
    if not getattr(contatto, "cliente", True):
        return None
    return {"condizioni": CondizioniCliente.objects.filter(contatto=contatto).select_related("listino").first(),
            "listini": Listino.objects.filter(azienda_id=contatto.azienda_id, attivo=True),
            "regole": RegolaSconto.objects.filter(cliente=contatto, attiva=True)[:5]}
