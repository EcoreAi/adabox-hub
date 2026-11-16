from theme.context_processors import theme as _theme   # core importa theme, mai il contrario

from . import attivita, azienda, barra, funzioni, licenza
from .registry import hooks, modules


def piattaforma(request):
    """theme.nav dalle app installate, app corrente con il suo menu, aziende dell'utente."""
    from django.conf import settings
    base = _theme(request)["theme"]
    sandbox = getattr(settings, "SANDBOX", False)
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"theme": base, "sandbox": sandbox}
    apps = modules.app_visibili(request.user)
    match = getattr(request, "resolver_match", None)
    in_dashboard = bool(match) and (match.view_name == "core:dashboard" or match.namespace.split(":")[0] in hooks.parti_dashboard())
    corrente = None if in_dashboard else modules.app_corrente(request, apps)     # le schede sono la navigazione
    voci_app, dashboard = barra.voci(apps)
    in_testa, resto = barra.in_testa(voci_app)             # es. l'assistente AI: di norma per primo
    nav = [*in_testa, dashboard, *resto]
    da_fare = attivita.da_fare_oggi(request.user)
    coda = [{"label": f"Attività · {da_fare}", "url_name": "core:attivita"}] if da_fare else []
    nav += coda
    scelta = barra.per_utente(request.user)
    principali, altre = barra.componi(voci_app, dashboard, scelta, corrente)
    principali = [*principali, *coda]                                    # le attività da fare restano in fondo
    return {
        "theme": {**base, "nav": nav, "nav_principale": principali, "nav_altre": altre, "nav_altre_gruppi": barra.gruppi(altre),
                  "nav_dashboard_attiva": in_dashboard},
        "apps": apps, "app_corrente": corrente, "menu_app": corrente["menu"] if corrente else [],
        "aziende": azienda.consentite(request.user), "azienda": getattr(request, "azienda", None),
        "voci_testata": hooks.voci_testata(request), "voci_profilo": modules.voci_profilo(request.user),
        "avviso_licenza": licenza.avviso() if request.user.has_perm("core.view_modulo") else "",
        "sandbox": sandbox, "funzioni": funzioni.PerPagina(),
    }
