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
SENZA_MODULO = "Serve il modulo Previsioni."      # il messaggio di chi usa le previsioni senza che il modulo ci sia


class ErrorePrevisione(Exception):
    """Un errore da mostrare così com'è all'utente."""


class StoriaInsufficiente(ErrorePrevisione):
    """La serie è vuota o troppo corta per prevedere: nella previsione per gruppo quel gruppo si esclude (gli altri
    errori, per esempio un campo sbagliato, fermano tutto)."""


class ErroreServizio(ErrorePrevisione):
    """Il servizio non ha dato una previsione (non configurato, irraggiungibile, ha rifiutato, risposta non valida):
    non dipende dai dati, quindi le previsioni salvate di prima restano."""


def url():
    try:
        return (parametri.leggi("previsioni.url_servizio") or "").strip().rstrip("/")
    except KeyError:
        return ""


def chiave():
    from .models import ServizioPrevisioni
    return ServizioPrevisioni.corrente().chiave


def abilitato(azienda=None, user=None):
    """Le previsioni ci sono: il modulo è installato, acceso (non spento dalla pagina Moduli), in licenza e, se si dà
    l'azienda, vale per lei (non riservato ad altre: Modulo.aziende). L'unico controllo per le pagine, Analisi, la chat
    e i lavori; l'indirizzo del servizio può mancare: lo dice `chiama` (è un guasto, non una licenza)."""
    return ("previsioni" in modules.manifests_attivi() and "previsioni" not in modules.disattivati()
            and licenza.ammesso("previsioni") and modules.per_azienda("previsioni", azienda, user))


def attivo(azienda=None, user=None):
    """`abilitato` e con l'indirizzo del servizio configurato."""
    return abilitato(azienda, user) and bool(url())


def chiama(percorso, dati):
    base = url()
    if not base:
        raise ErroreServizio("Il servizio di previsione non è configurato.")
    intestazioni = {"Content-Type": "application/json"}
    if segreto := chiave():
        intestazioni["Authorization"] = f"Bearer {segreto}"
    richiesta = urllib.request.Request(f"{base}{percorso}", data=json.dumps(dati).encode(), headers=intestazioni)
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
            return json.load(risposta)
    except urllib.error.HTTPError as e:
        dettaglio = e.read().decode(errors="replace")[:300]
        raise ErroreServizio(f"Il servizio di previsione ha rifiutato la richiesta: {dettaglio}") from e
    except Exception as e:
        log.warning("servizio di previsione non raggiungibile: %s", e)
        raise ErroreServizio("Il servizio di previsione non risponde: riprova tra poco.") from e
