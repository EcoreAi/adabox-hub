from django.utils.functional import SimpleLazyObject

from .azienda import corrente


class ModuloDisattivatoMiddleware:
    """Le pagine e le API di un modulo disattivato rispondono 404 con un avviso, per tutti: il modulo resta
    installato con i suoi dati e si riaccende dalla pagina Moduli."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.shortcuts import render

        from .registry.modules import disattivati
        modulo = modulo_di(request.path_info)
        # il database si interroga solo per gli indirizzi di un modulo (non per kernel, login, file statici)
        if modulo in settings.ADDONS_ATTIVI and modulo in disattivati():
            return render(request, "core/modulo_disattivato.html", status=404)
        return self.get_response(request)


def modulo_di(percorso):
    """Il modulo di un indirizzo: il namespace delle sue pagine, o /api/v1/<modulo>/ per le API."""
    from django.urls import Resolver404, resolve
    parti = percorso.strip("/").split("/")
    if len(parti) >= 3 and parti[0] == "api":
        return parti[2]
    try:
        return resolve(percorso).namespace.split(":")[0]
    except Resolver404:
        return None


class AziendaCorrenteMiddleware:
    """request.azienda: lazy, nessuna query se la pagina non la usa; None per l'anonimo."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            request.azienda = SimpleLazyObject(lambda: corrente(request))
        else:
            request.azienda = None
        return self.get_response(request)
