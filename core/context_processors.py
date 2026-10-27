from theme.context_processors import theme as _theme   # core importa theme, mai il contrario

from . import azienda
from .registry import modules


def piattaforma(request):
    """theme.nav dalle app installate, app corrente con il suo menu, aziende dell'utente."""
    base = _theme(request)["theme"]
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"theme": base}
    apps = modules.app_visibili(request.user)
    corrente = modules.app_corrente(request, apps)
    return {
        "theme": {**base, "nav": [{"label": a["label"], "url_name": a["url_name"]} for a in apps]},
        "apps": apps, "app_corrente": corrente, "menu_app": corrente["menu"] if corrente else [],
        "aziende": azienda.consentite(request.user), "azienda": getattr(request, "azienda", None),
    }
