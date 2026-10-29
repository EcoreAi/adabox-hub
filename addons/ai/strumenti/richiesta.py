"""Richiesta finta per usare le ModelView dall'assistente come dal browser: stesso utente, stessa azienda, stesse
personalizzazioni di Studio. I messaggi (messages.success...) dei bottoni si raccolgono invece di andare in
sessione, così l'esito torna nella chat."""
from django.conf import settings
from django.contrib.messages.storage.base import BaseStorage
from django.http import HttpRequest


class _Messaggi(BaseStorage):
    def __init__(self, request):
        super().__init__(request)
        self.raccolti = []

    def add(self, level, message, extra_tags=""):
        self.raccolti.append(str(message))

    def _get(self, *args, **kwargs):
        return [], True

    def _store(self, messages, response, *args, **kwargs):
        return []


def _host():
    return next((h for h in settings.ALLOWED_HOSTS if h and h != "*" and not h.startswith(".")), "localhost")


def nuova(utente, azienda=None, metodo="GET"):
    request = HttpRequest()
    request.method = metodo
    request.user, request.azienda = utente, azienda
    request.META.update({"HTTP_HOST": _host(), "SERVER_NAME": _host(), "SERVER_PORT": "80",
                         "HTTP_USER_AGENT": "assistente AI"})
    request.session = {}
    request._messages = _Messaggi(request)
    return request


def per(contesto, metodo="GET"):
    """La richiesta del contesto (una per turno e metodo: le letture in parallelo la condividono)."""
    chiave = f"richiesta_{metodo}"
    if chiave not in contesto.extra:
        contesto.extra[chiave] = nuova(contesto.utente, contesto.azienda, metodo)
    return contesto.extra[chiave]


def messaggi(request):
    return list(request._messages.raccolti)
