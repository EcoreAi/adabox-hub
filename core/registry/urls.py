"""URL dei moduli installati: un prefisso <slug>/ e un namespace <slug> per ciascuno.

Un modulo può dichiarare in `urls.py` anche `urlpatterns_radice`: indirizzi fuori dal suo prefisso, per i pochi casi in
cui il percorso lo fissa uno standard (es. `/.well-known/…`). Stanno alla radice senza namespace, quindi i nomi devono
essere unici e i middleware dei moduli (disattivato, dipartimenti) non li vedono: la vista controlla da sé."""
import importlib
import importlib.util

from django.conf import settings
from django.urls import include, path

from core.viste import registry


def patterns_moduli():
    registry.autodiscover(settings.ADDONS_ATTIVI)
    from . import hooks, modules
    applicazioni = {s for s, m in modules.manifests_attivi().items() if getattr(m, "application", False)}
    patterns, radice = [], []
    for slug in settings.ADDONS_ATTIVI:
        modulo = importlib.import_module(f"{slug}.urls") if importlib.util.find_spec(f"{slug}.urls") else None
        propri = getattr(modulo, "urlpatterns", [])
        radice += list(getattr(modulo, "urlpatterns_radice", []))
        aggiunte = [path(p["percorso"], p["vista"], name=p["nome"]) for p in hooks.pagine_app()
                    if slug in applicazioni and slug not in p["escluse"]]
        patterns.append(path(f"{slug}/", include((registry.urlpatterns(slug) + list(propri) + aggiunte, slug))))
    return patterns + radice
