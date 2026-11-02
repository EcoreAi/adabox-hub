"""Controllo della partita IVA nel VIES, il registro europeo degli operatori intracomunitari."""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from . import validatori

log = logging.getLogger("contatti.vies")
URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{paese}/vat/{numero}"
TIMEOUT = 8


class ViesNonDisponibile(Exception):
    pass


def controlla(nazione, partita_iva):
    """{"valido", "nome", "indirizzo"}. ViesNonDisponibile se il servizio non risponde (è solo un controllo in più)."""
    url = URL.format(paese=validatori.prefisso_iva(nazione), numero=urllib.parse.quote(partita_iva))
    richiesta = urllib.request.Request(url, headers={"User-Agent": "adabox-hub", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
            dati = json.load(risposta)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        log.warning("VIES non raggiungibile per %s: %s", nazione, e)
        raise ViesNonDisponibile from e
    if dati.get("isValid") is None or dati.get("userError") not in ("VALID", "INVALID"):
        raise ViesNonDisponibile
    pulito = lambda testo: "" if (testo or "").strip("- ") == "" else testo.strip()     # noqa: E731
    return {"valido": bool(dati["isValid"]), "nome": pulito(dati.get("name")), "indirizzo": pulito(dati.get("address"))}
