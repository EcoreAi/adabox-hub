from django import template

from ..burndown import disegna

register = template.Library()


@register.simple_tag
def burndown(sprint):
    return disegna(sprint)


@register.simple_tag
def sprint_in_corso(progetto):
    return progetto.sprint.filter(stato="attivo").order_by("inizio").first()


@register.simple_tag
def prossimi_rilasci(progetto):
    return progetto.rilasci.filter(stato="pianificato").order_by("data_prevista", "pk")[:3]
