from django import template

from helpdesk.guida import cerca
from helpdesk.models import Articolo

register = template.Library()


@register.simple_tag
def articoli_suggeriti(ticket):
    if ticket.fase.chiusa:
        return []
    return cerca(Articolo.objects.filter(azienda=ticket.azienda, pubblicato=True), f"{ticket.oggetto} {ticket.descrizione}", 3)
