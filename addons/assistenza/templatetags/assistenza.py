from django import template

register = template.Library()


@register.simple_tag
def dati_assistenza(ticket):
    from ..models import DatiTicket
    return DatiTicket.objects.filter(ticket=ticket).select_related("progetto", "compito__fase").first()


@register.simple_tag
def supporto_del_progetto(progetto):
    from ..models import Supporto
    return Supporto.objects.filter(progetto=progetto).select_related("team", "responsabile", "contratto").first()
