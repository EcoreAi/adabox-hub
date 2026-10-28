from theme.context_processors import theme as _theme   # core importa theme, mai il contrario

from . import attivita, azienda, barra
from .registry import hooks, modules


def piattaforma(request):
    """theme.nav dalle app installate, app corrente con il suo menu, aziende dell'utente."""
    base = _theme(request)["theme"]
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"theme": base}
    apps = modules.app_visibili(request.user)
    corrente = modules.app_corrente(request, apps)
    voci_app = [{"label": a["label"], "url_name": a["url_name"], "slug": a["slug"]} for a in apps]
    nav = [{"label": "Dashboard", "url_name": "core:dashboard"}, *voci_app]
    da_fare = attivita.da_fare_oggi(request.user)
    if da_fare:
        nav.append({"label": f"Attività · {da_fare}", "url_name": "core:attivita"})
    scelta = barra.leggi()
    principali, altre = barra.dividi(voci_app, corrente, scelta["quante"], scelta["fisse"])
    principali = [nav[0], *principali] + nav[len(voci_app) + 1:]          # Dashboard, app, Attività
    return {
        "theme": {**base, "nav": nav, "nav_principale": principali, "nav_altre": altre},
        "apps": apps, "app_corrente": corrente, "menu_app": corrente["menu"] if corrente else [],
        "aziende": azienda.consentite(request.user), "azienda": getattr(request, "azienda", None),
        "voci_testata": hooks.voci_testata(request),
    }
