"""Le chiamate ad Agate, con la libreria standard: niente dipendenze in più.

`trasporto` si sostituisce nei test. Gli errori di Agate arrivano con il suo titolo e dettaglio, in
italiano; la chiave non compare mai nei messaggi."""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

TIMEOUT = 10
TOLLERANZA_FIRMA = 300


class ErroreAgate(Exception):
    def __init__(self, messaggio, stato=None, dettaglio=""):
        super().__init__(messaggio)
        self.stato = stato
        self.dettaglio = dettaglio


def _user_agent():
    """Un nome proprio: alcuni proxy (Cloudflare) rifiutano lo User-Agent predefinito di Python."""
    from core import __version__
    return f"adabox-hub/{__version__} (Controllo AI)"


def _trasporto(metodo, url, intestazioni, corpo):
    richiesta = urllib.request.Request(url, data=corpo, headers={"User-Agent": _user_agent(), **intestazioni},
                                       method=metodo)
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:  # noqa: S310 (URL scelto dall'admin)
            return risposta.status, risposta.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


trasporto = _trasporto


def _invia(metodo, url, chiave, dati):
    intestazioni = {"Accept": "application/json"}
    if chiave:
        intestazioni["Authorization"] = f"Bearer {chiave}"
    corpo = None
    if dati is not None:
        corpo = json.dumps(dati, ensure_ascii=False, default=str).encode()
        intestazioni["Content-Type"] = "application/json"
    try:
        stato, testo = trasporto(metodo, url, intestazioni, corpo)
    except OSError as e:
        raise ErroreAgate(f"Agate non raggiungibile ({type(e).__name__})") from None
    try:
        risposta = json.loads(testo or b"{}")
    except ValueError:
        risposta = {}
    if not isinstance(risposta, dict):
        risposta = {}
    if stato >= 400:
        titolo, dettaglio = risposta.get("title"), risposta.get("detail")
        dettaglio = dettaglio if isinstance(dettaglio, str) else ""
        raise ErroreAgate(f"{titolo or f'HTTP {stato}'}: {dettaglio}".strip(": "), stato, dettaglio[:300])
    return stato, risposta


def chiama(collegamento, metodo, percorso, dati=None, chiave=None):
    """Con la chiave dell'assistente (`evaluate` + `llm`), salvo un'altra chiave indicata (`decide`, `sync`)."""
    url = collegamento.gateway_url.rstrip("/") + percorso
    return _invia(metodo, url, collegamento.chiave() if chiave is None else chiave, dati)[1]


def valuta(collegamento, strumento, argomenti, motivazione, attore):
    """`POST /v1/evaluate`: cosa dice Agate di questa azione."""
    corpo = {"proposal": {"tool": strumento, "params": argomenti, "rationale": motivazione[:2000],
                          "actor": {"kind": "llm", "id": attore[:100]}}}
    return chiama(collegamento, "POST", "/v1/evaluate", corpo)


def esito(collegamento, evaluation_id):
    """`GET /v1/evaluations/{id}`: verdetto e stato dell'approvazione, con lo scope evaluate."""
    return chiama(collegamento, "GET", f"/v1/evaluations/{evaluation_id}")


def modelli(collegamento):
    """I nomi logici dei modelli che l'azienda ha scelto in Agate per questa chiave."""
    return chiama(collegamento, "GET", "/v1/llm/models").get("data", [])


def connetti(gateway_url, codice, app):
    """`POST /v1/apps/connect` (§8.1): senza chiave, vale il codice `agc_`. Restituisce la risposta (201)."""
    return _invia("POST", gateway_url.rstrip("/") + "/v1/apps/connect", None, {"code": codice, "app": app})[1]


def decidi(collegamento, approval_id, decisione, chi, motivo=""):
    """`POST /v1/approvals/{id}/decide` con la chiave `decide` (§8.4), sempre a nome di una persona.
    (stato HTTP, risposta): 200 decisa, 202 `awaiting_confirmation` (doppia conferma)."""
    from urllib.parse import quote
    url = f"{collegamento.gateway_url.rstrip('/')}/v1/approvals/{quote(approval_id, safe='')}/decide"
    return _invia("POST", url, collegamento.chiave_decide(),
                  {"decision": decisione, "decided_by": chi, "reason": motivo[:1000]})


def sincronizza(collegamento, strumenti_interni=None):
    """`POST /v1/apps/sync` con la chiave `sync` (§8.1): Agate rilegge gli strumenti MCP di adabox (e quelli interni,
    se ci sono)."""
    dati = {} if strumenti_interni is None else {"internal_tools": strumenti_interni}
    return chiama(collegamento, "POST", "/v1/apps/sync", dati, chiave=collegamento.chiave_sync())


def verifica_firma(segreto, intestazione, corpo, adesso=None):
    """`X-Agate-Signature: t=<unix>,v1=<hmac-sha256>` come la calcola Agate. Solleva ValueError."""
    if not intestazione or not segreto:
        raise ValueError("firma assente")
    parti = dict(p.split("=", 1) for p in intestazione.split(",") if "=" in p)
    try:
        istante = int(parti["t"])
        ricevuta = parti["v1"]
    except (KeyError, ValueError):
        raise ValueError("firma malformata") from None
    attesa = hmac.new(segreto.encode(), f"{istante}.".encode() + corpo, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(ricevuta.encode("ascii", "ignore"), attesa.encode()):
        raise ValueError("firma non valida")
    if abs((adesso or int(time.time())) - istante) > TOLLERANZA_FIRMA:
        raise ValueError("firma scaduta")
    return istante
