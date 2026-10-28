from django import template

from core import allegati
from discuss import testo

register = template.Library()


@register.filter
def messaggio_html(corpo):
    return testo.rendi(corpo)


@register.filter
def allegati_messaggio(messaggio):
    return allegati.di(messaggio)


@register.filter
def iniziale(utente):
    return ((utente.get_full_name() or utente.username)[:1] if utente else "?").upper()


@register.filter
def titolo_canale(canale, utente):
    return canale.titolo_per(utente)
