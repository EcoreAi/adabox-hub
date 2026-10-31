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
    def __init__(self, messaggio, stato=None):
        super().__init__(messaggio)
        self.stato = stato


def _trasporto(metodo, url, intestazioni, corpo):
    richiesta = urllib.request.Request(url, data=corpo, headers=intestazioni, method=metodo)
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:  # noqa: S310 (URL scelto dall'admin)
            return risposta.status, risposta.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


trasporto = _trasporto


def chiama(collegamento, metodo, percorso, dati=None):
    url = collegamento.gateway_url.rstrip("/") + percorso
    intestazioni = {"Authorization": f"Bearer {collegamento.chiave()}", "Accept": "application/json"}
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
    if stato >= 400:
        titolo = risposta.get("title") if isinstance(risposta, dict) else None
        dettaglio = risposta.get("detail") if isinstance(risposta, dict) else None
        raise ErroreAgate(f"{titolo or f'HTTP {stato}'}: {dettaglio or ''}".strip(": "), stato)
    return risposta


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
