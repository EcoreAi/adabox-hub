"""Dashboard: KPI e grafici forniti dalle app installate (chiave `dashboard` del manifest).

La funzione di un'app riceve la richiesta e restituisce
    {"kpi": [{"valore": 4, "etichetta": "da fare", "url": "/todo/attivita/?f_stato=aperta"}, ...],
     "grafici": [{"titolo": "...", "tipo": "barre|linee|torta", "dati": [(etichetta, valore), ...], "url": "..."}]}
Il primo KPI è il numero grande della card; i conteggi vanno fatti con `queryset(request, Modello)`, che applica
azienda corrente, visibilità e permessi della ModelView del modello.
"""
import logging

from django.utils.safestring import mark_safe

from . import attivita, svg
from .lavori import risolvi
from .registry import modules

log = logging.getLogger("core.dashboard")


def queryset(request, modello):
    """Record del modello che l'utente vede (stesse regole della lista); vuoto senza permesso di vista."""
    from .viste import registry
    vista = registry.per_modello(modello)
    if vista is None or not vista.has_view_permission(request):
        return modello._default_manager.none()
    return vista.get_queryset(request)


def numero(valore):
    from .viste.gruppi import numero as formatta
    return formatta(valore)


def schede(request):
    """[{slug, label, icon, url, kpi, grafici}] per le app visibili all'utente che dichiarano una dashboard."""
    manifest = modules.manifests_attivi()
    risultato = []
    for app in modules.app_visibili(request.user):
        funzione = manifest[app["slug"]].dashboard if app["slug"] in manifest else None
        if not funzione:
            continue
        try:
            dati = risolvi(funzione)(request) or {}
        except Exception:                      # una app con un errore non deve rompere la dashboard
            log.exception("dashboard di %s non disponibile", app["slug"])
            continue
        risultato.append({**app, "kpi": dati.get("kpi", []), "grafici": dati.get("grafici", [])})
    return risultato


def scheda_attivita(request):
    """Card del kernel: le attività pianificate dell'utente."""
    mie = attivita.mie(request.user)
    totale = mie.count()
    if not totale:
        return None
    from django.urls import reverse
    return {"slug": "attivita", "label": "Le mie attività", "icon": "check", "url": reverse("core:attivita"),
            "kpi": [{"valore": attivita.da_fare_oggi(request.user), "etichetta": "oggi o scadute"},
                    {"valore": totale, "etichetta": "in tutto"}], "grafici": []}


def grafici(schede_app):
    """I grafici di tutte le app, già disegnati in SVG."""
    disegnati = []
    for scheda in schede_app:
        for g in scheda["grafici"]:
            dati = [(e, v) for e, v in g.get("dati", []) if v is not None]
            disegnati.append({"titolo": g["titolo"], "app": scheda["label"], "url": g.get("url") or scheda["url"],
                              "svg": mark_safe(svg.DISEGNI.get(g.get("tipo", "barre"), svg.barre)(dati, g["titolo"]))
                              if any(v for _, v in dati) else None})
    return disegnati
