from django import template

from magazzino import collegamenti
from magazzino.models import Consegna, Ricevimento

register = template.Library()


@register.simple_tag
def consegne_di(ordine):
    return collegamenti.di(ordine, Consegna)


@register.simple_tag
def ricevimenti_di(ordine):
    return collegamenti.di(ordine, Ricevimento)
