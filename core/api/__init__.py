"""API JSON del kernel: /api/v1/, sessione Django o token Bearer."""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from ninja import NinjaAPI
from ninja.errors import Throttled
from ninja.security import django_auth
from ninja.throttling import SimpleRateThrottle

from core import __version__

from .auth import TokenAuth


class LimitePerToken(SimpleRateThrottle):
    """Richieste al minuto per token (API_LIMITE, es. «120/m»); con la sessione del browser, per utente."""
    scope = "api"

    def get_rate(self):
        return getattr(settings, "API_LIMITE", "120/m") or None

    def allow_request(self, request):
        self.rate = self.get_rate()                     # letto ogni volta: si cambia dalle impostazioni senza riavvio
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request)

    def get_cache_key(self, request):
        token = getattr(request, "token_api", None)
        if token is not None:
            ident = f"t{token.pk}"
        elif getattr(request, "user", None) is not None and request.user.is_authenticated:
            ident = f"u{request.user.pk}"
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


api = NinjaAPI(title="adabox-hub", version=__version__, auth=[django_auth, TokenAuth()],
               docs_decorator=login_required, urls_namespace="api", throttle=[LimitePerToken()])


@api.exception_handler(Throttled)
def troppe_richieste(request, exc):
    risposta = api.create_response(request, {"detail": "troppe richieste: riprova tra poco"}, status=429)
    if exc.wait:
        risposta["Retry-After"] = str(int(exc.wait) + 1)
    return risposta

from . import fissi, modelli  # noqa: E402,F401  (registrano i router)
