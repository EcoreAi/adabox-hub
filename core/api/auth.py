from ninja.errors import HttpError
from ninja.security import HttpBearer

from core import azienda, registro
from core.models import Azienda, TokenApi


class TokenAuth(HttpBearer):
    def authenticate(self, request, token):
        t = TokenApi.verifica(token)
        if t:
            request.user = t.utente
            request.token_api = t
            registro.imposta(t.utente, "api")
            return t.utente
        return None


def controlla_token(request, modulo, scrittura):
    """Se la chiamata arriva con un token, deve permettere questo modulo e questa operazione."""
    token = getattr(request, "token_api", None)
    if token is not None and not token.permette(modulo, scrittura):
        raise HttpError(403, "questo token è in sola lettura" if scrittura and token.sola_lettura else f"questo token non vale per il modulo {modulo}")


def azienda_per(request):
    """X-Azienda se consentita (403 altrimenti), altrimenti l'azienda corrente. La imposta su request:
    il middleware ha girato prima dell'autenticazione via token, con l'utente anonimo."""
    consentite = azienda.consentite(request.user)
    richiesta = request.headers.get("X-Azienda")
    if richiesta:
        scelta = next((a for a in consentite if str(a.pk) == richiesta.strip()), None)
        if scelta is None:
            raise HttpError(403, f"azienda {richiesta} non consentita")
    else:
        scelta = azienda.corrente(request) if consentite else None
    request.azienda = scelta
    return scelta


__all__ = ["Azienda", "TokenAuth", "azienda_per", "controlla_token"]
