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


@register.filter
def codice_per(prodotto, cliente):
    """Il codice con cui il cliente chiama il prodotto ('' se non ne ha uno)."""
    from prodotti.models import codice_cliente
    trovato = codice_cliente(prodotto, cliente)
    return trovato.codice if trovato else ""
