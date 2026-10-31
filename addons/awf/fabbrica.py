"""Chiamate alla fabbrica degli agenti: collegamento, battito, stato, eventi (docs/plugin-api.md, §1-3 e §5).

Il token della fabbrica (`wpt_...`) si salva cifrato e non finisce mai nei log né a video. Il bearer del server MCP
nasce qui, al collegamento: se ne salva solo l'impronta e si mostra una volta sola a chi ha collegato. Ogni chiamata
ha un timeout di 10 secondi e non segue i redirect. HTTPS obbligatorio, salvo in sviluppo (`DEBUG`)."""
import hashlib
import hmac
import json
import logging
import re
import secrets
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core import cifratura

from . import agenti, operazioni
from .models import Collegamento

log = logging.getLogger("awf.fabbrica")

TIMEOUT = 10
CODICE_RE = re.compile(r"^wfc_[A-Za-z0-9_-]{32}$")
PREFISSO_BEARER = "awf_"
TIPI_EVENTO = ("record.assigned", "record.created", "record.mentioned", "receipt.ready")
MODELLO_RE = re.compile(r"^[a-z][a-z0-9_.]{1,79}$")
AGENTE_RE = re.compile(r"^[\w .'-]{1,100}$")

# Trasporto HTTP: funzione(metodo, url, intestazioni, corpo | None, timeout) -> (stato, corpo in byte).
# I test lo sostituiscono con uno finto: nessuna rete vera.
trasporto = None


class ErroreFabbrica(Exception):
    """La fabbrica non risponde o rifiuta la richiesta. Il messaggio è per le persone."""

    def __init__(self, messaggio, stato=None):
        super().__init__(messaggio)
        self.stato = stato


# ---------- bearer del server MCP ----------

def nuovo_bearer():
    return PREFISSO_BEARER + secrets.token_urlsafe(32)


def impronta(token):
    return hashlib.sha256(token.encode()).hexdigest()


def bearer_valido(presentato, impronta_salvata):
    """Confronto a tempo costante; senza impronta salvata (non collegato) è sempre falso, con lo stesso lavoro."""
    attesa = impronta_salvata or "0" * 64
    return hmac.compare_digest(impronta(presentato or ""), attesa) and bool(impronta_salvata)


def rigenera_bearer(collegamento=None):
    """Un bearer nuovo (il vecchio smette di valere): da mostrare una volta e da rimettere in Agate."""
    collegamento = collegamento or Collegamento.attuale()
    bearer = nuovo_bearer()
    collegamento.mcp_impronta, collegamento.mcp_indizio = impronta(bearer), bearer[:8]
    collegamento.save(update_fields=["mcp_impronta", "mcp_indizio"])
    return bearer


# ---------- HTTP ----------

class _NessunRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None                                     # il 3xx arriva al chiamante come errore HTTP


def _urllib(metodo, url, intestazioni, corpo, timeout):
    apri = urllib.request.build_opener(_NessunRedirect()).open
    richiesta = urllib.request.Request(url, data=corpo, method=metodo, headers=intestazioni)
    try:
        with apri(richiesta, timeout=timeout) as risposta:
            return risposta.status, risposta.read(1_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(1_000_000) if e.fp else b""
    except (urllib.error.URLError, OSError) as e:
        raise ErroreFabbrica(f"fabbrica non raggiungibile ({type(e).__name__})") from None


def controlla_url(valore, cosa):
    valore = (valore or "").strip()
    parti = urlsplit(valore)
    ammessi = ("https", "http") if settings.DEBUG else ("https",)
    if parti.scheme not in ammessi or not parti.netloc or parti.query or parti.fragment:
        raise ErroreFabbrica(f"indirizzo {cosa} non valido: serve https://host[/percorso]")
    return valore.rstrip("/")


def richiesta(metodo, percorso, *, forge_url, token=None, dati=None):
    """(stato HTTP, corpo JSON come dizionario). Solleva ErroreFabbrica se la fabbrica non risponde."""
    from core.registry.modules import manifests_attivi
    manifest = manifests_attivi().get("awf")
    intestazioni = {"Accept": "application/json",
                    "User-Agent": f"adabox-awf/{manifest.version if manifest else '1'}"}
    if token:
        intestazioni["Authorization"] = f"Bearer {token}"
    corpo = None
    if dati is not None:
        corpo = json.dumps(dati, ensure_ascii=False).encode()
        intestazioni["Content-Type"] = "application/json"
    stato, grezzo = (trasporto or _urllib)(metodo, forge_url + percorso, intestazioni, corpo, TIMEOUT)
    try:
        risposta = json.loads(grezzo or b"{}")
    except ValueError:
        risposta = {}
    return stato, risposta if isinstance(risposta, dict) else {}


def _dettaglio(corpo):
    d = corpo.get("detail")
    return f": {d[:200]}" if isinstance(d, str) and d else ""


# ---------- collegamento, battito, stato ----------

def collega(codice, forge_url, base_url, azienda=None):
    """Collega l'istanza con il codice `wfc_...` (§1). Restituisce (collegamento, bearer MCP da mostrare una volta).
    Sostituisce un collegamento precedente: il vecchio bearer smette di valere, il segreto dei webhook resta."""
    codice = (codice or "").strip()
    if not CODICE_RE.match(codice):
        raise ErroreFabbrica("codice di collegamento non valido: wfc_ seguito da 32 caratteri")
    forge = controlla_url(forge_url, "della fabbrica")
    base = controlla_url(base_url, "di questa istanza")
    dati = {"code": codice, "kind": "django", "version": operazioni.versione(), "base_url": base,
            "operations": [e.dichiarazione() for e in operazioni.esposte()]}
    stato, corpo = richiesta("POST", "/api/plugins/connect", forge_url=forge, dati=dati)
    if stato == 404:
        raise ErroreFabbrica("codice sconosciuto o scaduto", stato)
    if stato == 409:
        raise ErroreFabbrica("codice già usato", stato)
    if stato == 422:
        raise ErroreFabbrica(f"la fabbrica ha rifiutato i dati{_dettaglio(corpo)}", stato)
    if stato != 201:
        raise ErroreFabbrica(f"risposta inattesa della fabbrica (HTTP {stato})", stato)
    token = corpo.get("token")
    if not isinstance(token, str) or not token.startswith("wpt_"):
        raise ErroreFabbrica("la fabbrica non ha restituito un token valido", stato)
    ingaggio = corpo.get("engagement") if isinstance(corpo.get("engagement"), dict) else {}
    bearer = nuovo_bearer()
    with transaction.atomic():
        c = Collegamento.attuale()
        c.forge_url, c.base_url = forge, base
        c.install_id = str(corpo.get("install_id") or "")[:100]
        c.token_cifrato = cifratura.cifra(token)
        c.mcp_impronta, c.mcp_indizio = impronta(bearer), bearer[:8]
        c.versione = dati["version"]
        c.ultimo_stato, c.stato_il, c.ultimo_errore = ingaggio, timezone.now(), ""
        c.collegato_il = timezone.now()
        if azienda is not None:
            c.azienda = azienda
        elif c.azienda is None:
            from core.models import Azienda
            c.azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
        c.save()
    agenti.sincronizza(ingaggio, c.azienda)
    log.info("collegato alla fabbrica %s (installazione %s)", forge, c.install_id)
    return c, bearer


def _collegamento():
    c = Collegamento.attuale()
    if not c.collegato:
        raise ErroreFabbrica("non collegato alla fabbrica: incolla il codice di collegamento")
    return c


def _errore(c, messaggio, stato=None):
    c.ultimo_errore = messaggio[:300]
    c.save(update_fields=["ultimo_errore"])
    return ErroreFabbrica(messaggio, stato)


def _ingaggio(c, stato, corpo):
    if stato == 401:
        raise _errore(c, "la fabbrica non riconosce il token: ricollega con un codice nuovo", stato)
    if stato != 200 or not isinstance(corpo.get("engagement"), dict):
        raise _errore(c, f"risposta inattesa della fabbrica (HTTP {stato})", stato)
    c.ultimo_stato, c.stato_il, c.ultimo_errore = corpo["engagement"], timezone.now(), ""
    c.save(update_fields=["ultimo_stato", "stato_il", "ultimo_errore", "versione"])
    agenti.sincronizza(c.ultimo_stato, c.azienda)
    return c.ultimo_stato


def battito():
    """Battito (§2): dichiara la versione (che cambia con le operazioni ammesse) e riceve lo stato dell'ingaggio."""
    c = _collegamento()
    c.versione = operazioni.versione()
    try:
        stato, corpo = richiesta("POST", "/api/plugins/heartbeat", forge_url=c.forge_url, token=c.token(),
                                 dati={"version": c.versione})
    except ErroreFabbrica as e:
        raise _errore(c, str(e)) from None
    return _ingaggio(c, stato, corpo)


def stato_ingaggio():
    """Stato dell'ingaggio (§3), salvato come ultimo stato noto."""
    c = _collegamento()
    try:
        stato, corpo = richiesta("GET", "/api/plugins/status", forge_url=c.forge_url, token=c.token())
    except ErroreFabbrica as e:
        raise _errore(c, str(e)) from None
    return _ingaggio(c, stato, corpo)


# ---------- eventi (§5): solo modello e id, mai testo ----------

def evento(tipo, modello, record_id, agente=None):
    """Il corpo dell'evento, controllato: un tipo previsto, un nome di modello o vista, un id intero, il nome di
    un agente. Nient'altro può passare, quindi nessun testo dei record."""
    if tipo not in TIPI_EVENTO:
        raise ValueError("tipo di evento non previsto")
    if not isinstance(modello, str) or not MODELLO_RE.match(modello):
        raise ValueError("nome del modello non valido")
    if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id < 1:
        raise ValueError("id del record non valido: un intero positivo")
    if agente is not None and not (isinstance(agente, str) and AGENTE_RE.match(agente)):
        raise ValueError("nome dell'agente non valido")
    return {"type": tipo, "model": modello, "record_id": record_id, "agent": agente}


def invia_evento(tipo, modello, record_id, agente=None):
    dati = evento(tipo, modello, record_id, agente)
    c = _collegamento()
    stato, corpo = richiesta("POST", "/api/plugins/events", forge_url=c.forge_url, token=c.token(), dati=dati)
    if stato == 429:
        raise ErroreFabbrica("troppi eventi: la fabbrica ne accetta 600 l'ora", stato)
    if stato == 401:
        raise ErroreFabbrica("la fabbrica non riconosce il token: ricollega con un codice nuovo", stato)
    if stato not in (200, 202):
        raise ErroreFabbrica(f"evento rifiutato dalla fabbrica (HTTP {stato})", stato)
    return corpo
