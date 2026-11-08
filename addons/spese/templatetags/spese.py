from django import template

register = template.Library()


@register.simple_tag
def pagamento_nota(nota):
    """Il movimento bancario abbinato al rimborso della nota (se c'è Banca)."""
    from spese import riaddebito
    return riaddebito.pagamento_di(nota)
