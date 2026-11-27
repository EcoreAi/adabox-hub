"""Specialisti locali di adabox come strumenti dell'assistente: il decisore (protocollo di Jev sopra EmbeddingGemma).
Servizio sulla rete interna, URL nelle impostazioni, spento se l'URL è vuoto.

Le previsioni non stanno più qui: il motore è nel modulo Previsioni (`previsioni.motore`).
"""
import json
import logging
import urllib.error
import urllib.request

from .strumenti import ErroreStrumento

log = logging.getLogger("ai.specialisti")

TIMEOUT = 120


def url(chiave):
    """L'URL di un servizio dalle impostazioni ("" se non c'è o se l'impostazione non esiste)."""
    from core import parametri
    try:
        return (parametri.leggi(f"ai.{chiave}") or "").strip().rstrip("/")
    except KeyError:
        return ""


def chiama(chiave, percorso, dati, nome):
    base = url(chiave)
    if not base:
        raise ErroreStrumento(f"Il servizio di {nome} non è configurato.")
    richiesta = urllib.request.Request(f"{base}{percorso}", data=json.dumps(dati).encode(),
                                       headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
            return json.load(risposta)
    except urllib.error.HTTPError as e:
        dettaglio = e.read().decode(errors="replace")[:300]
        raise ErroreStrumento(f"Il servizio di {nome} ha rifiutato la richiesta: {dettaglio}")
    except Exception as e:
        log.warning("servizio di %s non raggiungibile: %s", nome, e)
        raise ErroreStrumento(f"Il servizio di {nome} non risponde: riprova tra poco.")


# ---------- decisore ----------

TIPI_DOMANDA = {"si_no": "noul", "scelta": "choice", "punteggio": "score"}


def decidi(testo, domanda, tipo="si_no", opzioni=None):
    if tipo not in TIPI_DOMANDA:
        raise ErroreStrumento("«tipo» è si_no, scelta o punteggio.")
    q = {"type": TIPI_DOMANDA[tipo], "instructions": domanda}
    if tipo == "scelta":
        if not isinstance(opzioni, dict) or not opzioni:
            raise ErroreStrumento("Per «scelta» servono le opzioni {nome: descrizione}.")
        q["criteria"] = {str(k): str(v) for k, v in opzioni.items()}
    elif tipo == "punteggio":
        if not isinstance(opzioni, list) or not 2 <= len(opzioni) <= 10:
            raise ErroreStrumento("Per «punteggio» servono da 2 a 10 livelli in ordine, dal più basso.")
        q["criteria"] = [str(o) for o in opzioni]
    risposta = chiama("url_decider", "/v1/systemone", {"state": testo[:8000], "questions": {"d": q}}, "decisione")
    return risposta.get("answers", {}).get("d", {})
