from django.utils.functional import SimpleLazyObject

from .azienda import corrente


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
