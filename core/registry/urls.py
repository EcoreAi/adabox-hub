"""URL dei moduli installati: un prefisso <slug>/ e un namespace <slug> per ciascuno."""
import importlib
import importlib.util

from django.conf import settings
from django.urls import include, path

from core.viste import registry


def patterns_moduli():
    registry.autodiscover(settings.ADDONS_ATTIVI)
    patterns = []
    for slug in settings.ADDONS_ATTIVI:
        propri = importlib.import_module(f"{slug}.urls").urlpatterns if importlib.util.find_spec(f"{slug}.urls") else []
        patterns.append(path(f"{slug}/", include((registry.urlpatterns(slug) + list(propri), slug))))
    return patterns
