"""Dati delle sezioni sul fido nei dettagli del contatto e del preventivo."""
from django import template

from vendite import fido

register = template.Library()


@register.simple_tag
def fido_del_contatto(contatto):
    return fido.situazione(contatto) if contatto.cliente else None


@register.simple_tag
def fido_dell_ordine(ordine):
    return fido.controllo(ordine) if ordine.modificabile else None
