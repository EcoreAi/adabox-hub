from theme.context_processors import theme as _theme   # core importa theme, mai il contrario

from . import attivita, azienda
from .registry import modules


def piattaforma(request):
    """theme.nav dalle app installate, app corrente con il suo menu, aziende dell'utente."""
    base = _theme(request)["theme"]
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"theme": base}
    apps = modules.app_visibili(request.user)
    corrente = modules.app_corrente(request, apps)
    nav = [{"label": a["label"], "url_name": a["url_name"]} for a in apps]
    if (da_fare := attivita.da_fare_oggi(request.user)):
        nav.append({"label": f"Attività · {da_fare}", "url_name": "core:attivita"})
    return {
        "theme": {**base, "nav": nav},
        "apps": apps, "app_corrente": corrente, "menu_app": corrente["menu"] if corrente else [],
        "aziende": azienda.consentite(request.user), "azienda": getattr(request, "azienda", None),
    }
