"""Filtri per le stampe dei prodotti: WeasyPrint legge le immagini dal disco, non dalla vista protetta."""
from django import template

from prodotti import immagini

register = template.Library()


@register.filter
def immagine_stampa(prodotto):
    """file:// dell'immagine principale del prodotto ('' se non ne ha)."""
    return immagini.uri_file(immagini.principale(prodotto))


@register.filter
def file_stampa(campo):
    """file:// di un campo immagine (es. le foto della galleria)."""
    return immagini.uri_file(campo.name if campo else "")
