from theme.context_processors import theme as _theme   # core importa theme, mai il contrario

from . import attivita, azienda, barra, licenza
from .registry import hooks, modules


def piattaforma(request):
    """theme.nav dalle app installate, app corrente con il suo menu, aziende dell'utente."""
    base = _theme(request)["theme"]
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"theme": base}
    apps = modules.app_visibili(request.user)
    corrente = modules.app_corrente(request, apps)
    voci_app = [{"label": a["nav_label"], "url_name": a["url_name"], "slug": a["slug"], "categoria": a["category"]} for a in apps]
    in_testa, resto = barra.in_testa(voci_app)             # es. l'assistente AI: di norma per primo
    dashboard = {"label": "Dashboard", "url_name": "core:dashboard", "slug": barra.DASHBOARD, "categoria": "Direzione"}
    nav = [*in_testa, dashboard, *resto]
    da_fare = attivita.da_fare_oggi(request.user)
    coda = [{"label": f"Attività · {da_fare}", "url_name": "core:attivita"}] if da_fare else []
    nav += coda
    scelta = barra.per_utente(request.user)
    principali, altre = barra.componi(voci_app, dashboard, scelta, corrente)
    principali = [*principali, *coda]                                    # le attività da fare restano in fondo
    return {
        "theme": {**base, "nav": nav, "nav_principale": principali, "nav_altre": altre, "nav_altre_gruppi": barra.gruppi(altre)},
        "apps": apps, "app_corrente": corrente, "menu_app": corrente["menu"] if corrente else [],
        "aziende": azienda.consentite(request.user), "azienda": getattr(request, "azienda", None),
        "voci_testata": hooks.voci_testata(request), "voci_profilo": modules.voci_profilo(request.user),
        "avviso_licenza": licenza.avviso() if request.user.has_perm("core.view_modulo") else "",
    }
