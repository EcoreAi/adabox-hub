"""Filtri per le pagine di AWF: `{% load awf %}`."""
from django import template

from ..squadre import nome_pulito

register = template.Library()


@register.filter
def nome_squadra(nome):
    """«Lead e CRM (adabox-hub)» → «Lead e CRM»: anche per i nomi salvati prima e per il titolo del contratto."""
    return nome_pulito(nome if isinstance(nome, str) else "")
