from django import template

from fatturazione.operazioni import fatture_attive

register = template.Library()


@register.simple_tag
def ordine_fatturabile(ordine):
    return ordine.stato == "confermato" and not fatture_attive(ordine)
