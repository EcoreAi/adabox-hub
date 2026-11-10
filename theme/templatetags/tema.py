import os
from pathlib import Path

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def statico(percorso):
    """URL di un file statico con la sua data di modifica: dopo un aggiornamento il browser scarica la versione nuova
    invece di usare la copia in cache (i file statici hanno una cache lunga e nomi senza versione)."""
    url = static(percorso)
    if Path(url).name != Path(percorso).name:                        # ha già l'impronta (core.storage.StaticConImpronta)
        return url
    pubblicato = Path(settings.STATIC_ROOT or "") / percorso         # la copia che nginx serve davvero, non il sorgente
    file = pubblicato if settings.STATIC_ROOT and pubblicato.exists() else finders.find(percorso)
    try:
        return f"{url}?v={int(os.path.getmtime(file))}" if file else url
    except OSError:
        return url
