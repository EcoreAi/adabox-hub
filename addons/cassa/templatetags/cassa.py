from django import template

register = template.Library()


@register.simple_tag
def riepilogo_cassa(cassa):
    from cassa import operazioni
    return operazioni.riepilogo(cassa)
