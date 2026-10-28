from django.conf import settings

from theme.context_processors import theme as _theme   # core importa theme, mai il contrario

from . import attivita, azienda
from .registry import hooks, modules


def dividi_nav(voci_app, corrente=None, quante=None):
    """(principali, altre): le prime `quante` app restano nella barra, le altre vanno nel menu "Altre".
    L'app in cui si trova l'utente è sempre tra le principali (al posto dell'ultima)."""
    quante = settings.NAV_APP_VISIBILI if quante is None else quante
    if len(voci_app) <= quante + 1:                       # una sola in più: inutile un menu per lei
        return voci_app, []
    principali, altre = voci_app[:quante], voci_app[quante:]
    slug = corrente["slug"] if corrente else None
    attiva = next((v for v in altre if v["slug"] == slug), None)
    if attiva is not None and principali:
        altre = [principali[-1], *[v for v in altre if v is not attiva]]
        principali = [*principali[:-1], attiva]
    return principali, altre


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
    principali, altre = dividi_nav(voci_app, corrente)
    principali = [nav[0], *principali] + nav[len(voci_app) + 1:]          # Dashboard, app, Attività
    return {
        "theme": {**base, "nav": nav, "nav_principale": principali, "nav_altre": altre},
        "apps": apps, "app_corrente": corrente, "menu_app": corrente["menu"] if corrente else [],
        "aziende": azienda.consentite(request.user), "azienda": getattr(request, "azienda", None),
        "voci_testata": hooks.voci_testata(request),
    }
