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


@register.simple_tag
def accesso_del_contatto(contatto):
    from ..models import AccessoPortale
    return AccessoPortale.objects.filter(contatto=contatto).select_related("utente").first()
