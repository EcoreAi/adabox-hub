"""ASGI: in produzione lo usa solo il servizio `stream` (uvicorn) per lo streaming dell'AI (/ai/flusso/);
il resto dell'applicazione resta su gunicorn (WSGI)."""
import os
import signal

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_app = get_asgi_application()

from core.management.commands.worker import impronta_moduli  # noqa: E402  (dopo il setup di Django)

_impronta = impronta_moduli()


async def application(scope, receive, send):
    """Se i moduli installati cambiano, il processo risponde 503 e si chiude: il supervisore di uvicorn ne
    avvia uno nuovo con il codice aggiornato (come fa il worker)."""
    if scope["type"] == "http" and impronta_moduli() != _impronta:
        await send({"type": "http.response.start", "status": 503,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"retry-after", b"2")]})
        await send({"type": "http.response.body", "body": "Servizio in riavvio, riprova.".encode()})
        os.kill(os.getpid(), signal.SIGTERM)
        return
    await django_app(scope, receive, send)
