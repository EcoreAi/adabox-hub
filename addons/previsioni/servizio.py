"""Il client del servizio di previsione (Timestral): URL nelle impostazioni, chiave cifrata, spento se l'URL è vuoto.

Come `ai.specialisti.chiama`: la rete interna è ammessa perché l'URL lo decide il Global Admin."""
import json
import logging
import urllib.error
import urllib.request

from core import licenza, parametri
from core.registry import modules

log = logging.getLogger("previsioni.servizio")

TIMEOUT = 120


class ErrorePrevisione(Exception):
    """Un errore da mostrare così com'è all'utente."""


def url():
    try:
        return (parametri.leggi("previsioni.url_servizio") or "").strip().rstrip("/")
    except KeyError:
        return ""


def chiave():
    from .models import ServizioPrevisioni
    return ServizioPrevisioni.corrente().chiave


def attivo():
    return ("previsioni" in modules.manifests_attivi() and licenza.ammesso("previsioni") and bool(url()))


def chiama(percorso, dati):
    base = url()
    if not base:
        raise ErrorePrevisione("Il servizio di previsione non è configurato.")
    intestazioni = {"Content-Type": "application/json"}
    if segreto := chiave():
        intestazioni["Authorization"] = f"Bearer {segreto}"
    richiesta = urllib.request.Request(f"{base}{percorso}", data=json.dumps(dati).encode(), headers=intestazioni)
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
            return json.load(risposta)
    except urllib.error.HTTPError as e:
        dettaglio = e.read().decode(errors="replace")[:300]
        raise ErrorePrevisione(f"Il servizio di previsione ha rifiutato la richiesta: {dettaglio}") from e
    except Exception as e:
        log.warning("servizio di previsione non raggiungibile: %s", e)
        raise ErrorePrevisione("Il servizio di previsione non risponde: riprova tra poco.") from e
