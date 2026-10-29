import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def statico(percorso):
    """URL di un file statico con la sua data di modifica: dopo un aggiornamento il browser scarica la versione nuova
    invece di usare la copia in cache (i file statici hanno una cache lunga e nomi senza versione)."""
    file = finders.find(percorso)
    try:
        return f"{static(percorso)}?v={int(os.path.getmtime(file))}" if file else static(percorso)
    except OSError:
        return static(percorso)
