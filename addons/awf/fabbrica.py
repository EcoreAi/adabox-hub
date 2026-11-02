"""Chiamate alla fabbrica degli agenti: collegamento, battito, stato, eventi, catalogo e richieste d'ingaggio
(docs/plugin-api.md, §1-3, §5 e §7).

Il token della fabbrica (`wpt_...`) e quello di una richiesta d'ingaggio (`wfr_...`) si salvano cifrati e non
finiscono mai nei log né a video. Il bearer del server MCP nasce qui, al collegamento con il codice o quando lo chiede
una persona dopo una richiesta approvata: se ne salva solo l'impronta e si mostra una volta sola. Ogni chiamata
ha un timeout di 10 secondi e non segue i redirect. HTTPS obbligatorio, salvo in sviluppo (`DEBUG`)."""
import datetime
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core import cifratura

from . import agenti, operazioni, squadre
from .models import Collegamento, RichiestaAgenti

log = logging.getLogger("awf.fabbrica")

TIMEOUT = 10
CODICE_RE = re.compile(r"^wfc_[A-Za-z0-9_-]{32}$")
PREFISSO_BEARER = "awf_"
TIPI_EVENTO = ("record.assigned", "record.created", "record.mentioned", "receipt.ready")
MODELLO_RE = re.compile(r"^[a-z][a-z0-9_.]{1,79}$")
AGENTE_RE = re.compile(r"^[\w .'-]{1,100}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ORA_RE = re.compile(r"^([01]?\d|2[0-3])[:.][0-5]\d$")
DURATA_CATALOGO = 600                                   # secondi: il listino cambia di rado
STATI_RICHIESTA = {"received": RichiestaAgenti.INVIATA, "proposed": RichiestaAgenti.DA_APPROVARE,
                   "connected": RichiestaAgenti.COLLEGATA, "rejected": RichiestaAgenti.RIFIUTATA,
                   "withdrawn": RichiestaAgenti.RITIRATA}

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
    bearer = nuovo_bearer()
    c = completa(forge, base, token, corpo.get("install_id"), corpo.get("engagement"), dati["version"], azienda,
                 bearer=bearer)
    return c, bearer


def completa(forge, base, token, install_id, ingaggio, versione, azienda=None, bearer=None, dopo_il_salvataggio=None,
             tieni_bearer=False):
    """La parte comune del collegamento (§1) e della richiesta approvata (§7.3): c'è un token `wpt_...` e un
    ingaggio. Salva il token cifrato, l'installazione, la versione e lo stato, sceglie l'azienda e crea gli agenti.
    Con `bearer` imposta il nuovo bearer MCP. Senza: con `tieni_bearer` resta quello che l'azienda ha già dato ad
    Agate preparando la richiesta (gli strumenti della squadra devono essere attivi in Agate prima della proposta);
    altrimenti si toglie (era di un'altra installazione) e quello nuovo lo genera una persona, che deve vederlo.
    `dopo_il_salvataggio` gira nella stessa transazione."""
    ingaggio = ingaggio if isinstance(ingaggio, dict) else {}
    with transaction.atomic():
        c = Collegamento.attuale()
        c.forge_url, c.base_url = forge, base
        c.install_id = str(install_id or "")[:100]
        c.token_cifrato = cifratura.cifra(token)
        if bearer:
            c.mcp_impronta, c.mcp_indizio = impronta(bearer), bearer[:8]
        elif not tieni_bearer:
            c.mcp_impronta, c.mcp_indizio = "", ""
        c.versione = versione
        c.ultimo_stato, c.stato_il, c.ultimo_errore = ingaggio, timezone.now(), ""
        c.collegato_il = timezone.now()
        if azienda is not None:
            c.azienda = azienda
        elif c.azienda is None:
            from core.models import Azienda
            c.azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
        c.save()
        if dopo_il_salvataggio is not None:
            dopo_il_salvataggio(c)
    agenti.sincronizza(ingaggio, c.azienda)
    log.info("collegato alla fabbrica %s (installazione %s)", forge, c.install_id)
    return c


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


# ---------- catalogo e richieste d'ingaggio (§7): la squadra si chiede dal gestionale ----------

def indirizzo_fabbrica():
    """L'indirizzo della fabbrica: quello del collegamento o, se manca, `AWF_FORGE_URL` (impostazioni o ambiente)."""
    return (Collegamento.attuale().forge_url or getattr(settings, "AWF_FORGE_URL", "")
            or os.environ.get("AWF_FORGE_URL", "")).strip()


def _forge(forge_url=None):
    valore = forge_url or indirizzo_fabbrica()
    if not valore:
        raise ErroreFabbrica("indirizzo del negozio degli agenti non impostato: indicalo in Agenti AI → Negozio")
    return controlla_url(valore, "della fabbrica")


def _testo(valore, massimo):
    return valore.strip()[:massimo] if isinstance(valore, str) else ""


def _intero(valore, minimo=0):
    if isinstance(valore, bool):
        return None
    try:
        n = int(valore)
    except (TypeError, ValueError):
        return None
    return n if n >= minimo else None


def _operazione(o):
    effetto = o.get("effect") if o.get("effect") in ("read", "write", "irreversible") else "irreversible"
    return {"tool": _testo(o.get("tool"), 100), "view": _testo(o.get("view"), 80), "effect": effetto,
            "risk": _testo(o.get("risk"), 10), "line": _testo(o.get("line"), 300)}


def _testi(valore, quanti, massimo):
    return [x for x in (_testo(v, massimo) for v in (valore if isinstance(valore, list) else [])[:quanti]) if x]


def _vetrina(v):
    """La vetrina facoltativa della squadra (§7.1, `showcase`): solo testi semplici, con i limiti del contratto.
    Quello che manca le pagine lo ricavano da descrizione, ruoli e operazioni."""
    if not isinstance(v, dict):
        return {}
    giornata = [{"ora": _testo(g.get("time"), 5) if ORA_RE.match(_testo(g.get("time"), 5)) else "",
                 "testo": _testo(g.get("text"), 300)}
                for g in (v.get("day") if isinstance(v.get("day"), list) else [])[:8] if isinstance(g, dict)]
    domande = [{"domanda": _testo(f.get("q"), 300), "risposta": _testo(f.get("a"), 1000)}
               for f in (v.get("faq") if isinstance(v.get("faq"), list) else [])[:6] if isinstance(f, dict)]
    return {"icona": _testo(v.get("icon"), 8), "slogan": _testo(v.get("tagline"), 200),
            "vantaggi": _testi(v.get("benefits"), 5, 300), "giornata": [g for g in giornata if g["testo"]],
            "mai": _testi(v.get("never"), 6, 300), "domande": [d for d in domande if d["domanda"] and d["risposta"]]}


def _squadra(t):
    """Una squadra del listino, controllata: solo i campi che servono, con i tipi attesi. None se non valida."""
    if not isinstance(t, dict) or not isinstance(t.get("slug"), str) or not SLUG_RE.match(t["slug"]):
        return None
    versione = _intero(t.get("version", 1), 1)
    if versione is None:
        return None
    prezzo = t.get("price") if isinstance(t.get("price"), dict) else {}
    tetti = t.get("caps") if isinstance(t.get("caps"), dict) else {}
    return {
        "slug": t["slug"], "versione": versione,
        "nome": squadre.nome_pulito(_testo(t.get("name"), 200)) or t["slug"],
        "reparto": _testo(t.get("department"), 60).lower(), "descrizione": _testo(t.get("description"), 2000),
        "giorni_prova": _intero(t.get("observe_days"), 0) or 0,
        "membri": [{"ruolo": _testo(m.get("role"), 100), "nome": _testo(m.get("name"), 100),
                    "descrizione": _testo(m.get("description"), 500)}
                   for m in t.get("members") or [] if isinstance(m, dict) and _testo(m.get("name"), 100)],
        "operazioni": [_operazione(o) for o in t.get("operations") or [] if isinstance(o, dict)
                       and _testo(o.get("tool"), 100)],
        "prezzo": {k: v for k, v in prezzo.items() if isinstance(k, str) and isinstance(v, (str, int, float))
                   and not isinstance(v, bool)},
        "tetti": {k: v for k, v in tetti.items() if isinstance(k, str) and k.isidentifier()
                  and (v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)))},
        "vetrina": _vetrina(t.get("showcase"))}


def _chiave_catalogo(forge, reparto):
    return "awf:catalogo:" + hashlib.sha256(f"{forge}|{reparto}".encode()).hexdigest()


def catalogo(reparto=None, forge_url=None):
    """Le squadre del listino per adabox (§7.1, pubblico), eventualmente di un reparto. Tenute 10 minuti."""
    forge = _forge(forge_url)
    reparto = (reparto or "").strip().lower()[:60]
    chiave = _chiave_catalogo(forge, reparto)
    squadre = cache.get(chiave)
    if squadre is not None:
        return squadre
    parametri = {"kind": "django", "saas": "adabox", **({"department": reparto} if reparto else {})}
    stato, corpo = richiesta("GET", f"/api/catalog?{urlencode(parametri)}", forge_url=forge)
    if stato != 200 or not isinstance(corpo.get("teams"), list):
        raise ErroreFabbrica(f"catalogo non disponibile (HTTP {stato})", stato)
    squadre = [s for s in map(_squadra, corpo["teams"]) if s is not None]
    cache.set(chiave, squadre, DURATA_CATALOGO)
    return squadre


def dimentica_catalogo(forge_url=None, *reparti):
    forge = _forge(forge_url)
    cache.delete_many([_chiave_catalogo(forge, r) for r in ("", *reparti)])


def squadra(slug, forge_url=None):
    """La squadra del listino con questo slug, o None."""
    return next((s for s in catalogo(forge_url=forge_url) if s["slug"] == slug), None)


def _agate():
    """Il blocco facoltativo `agate` della richiesta, dal modulo agate se è attivo e collegato. Con il codice per la
    fabbrica (`factory_code`, dal collegamento ad Agate con un codice) in **ogni** richiesta (§8.2): la fabbrica si
    collega all'Agate dell'azienda da sola e propone da sola il contratto (§8.3)."""
    from core.registry.modules import disattivati
    if "agate" not in settings.ADDONS_ATTIVI or "agate" in disattivati():
        return None
    try:
        from agate.models import Collegamento as CollegamentoAgate
        a = CollegamentoAgate.attuale()
    except Exception:                                   # modulo non migrato o rotto: la richiesta parte lo stesso
        log.warning("collegamento ad Agate non leggibile", exc_info=True)
        return None
    if a is None or not a.gateway_url:
        return None
    blocco = {k: v for k, v in {"gateway_url": a.gateway_url, "console_url": a.console_url}.items() if v}
    c = Collegamento.attuale()
    if c.factory_code_cifrato:
        try:
            blocco["factory_code"] = c.factory_code()
        except cifratura.SegretoIlleggibile:
            log.warning("codice per la fabbrica illeggibile: la richiesta parte senza")
    return blocco


def richiedi(team, versione, settimane, note="", utente=None, azienda=None, base_url=""):
    """Chiede alla fabbrica una squadra del catalogo (§7.2). Restituisce la `RichiestaAgenti` salvata, con il token
    `wfr_...` cifrato. Le operazioni dichiarate sono quelle ammesse ora, come nel collegamento con il codice."""
    from core.models import Azienda
    forge = _forge()
    s = squadra(team, forge_url=forge)
    if s is None:
        raise ErroreFabbrica("squadra sconosciuta o non più in catalogo", 404)
    versione = s["versione"] if versione in (None, "") else _intero(versione, 1)
    settimane = _intero(settimane, 1)
    if versione is None:
        raise ErroreFabbrica("versione della squadra non valida")
    if settimane is None or settimane > 52:
        raise ErroreFabbrica("settimane: un numero da 1 a 52")
    note = (note or "").strip()
    if len(note) > 1000:
        raise ErroreFabbrica("note troppo lunghe: al massimo 1000 caratteri")
    c = Collegamento.attuale()
    base = controlla_url(base_url or c.base_url or settings.SITO_URL, "di questa istanza")
    azienda = azienda or c.azienda or Azienda.objects.filter(attiva=True).order_by("pk").first()
    if azienda is None:
        raise ErroreFabbrica("nessuna azienda attiva per cui chiedere la squadra")
    contatto = (utente.get_full_name() or utente.get_username()) if utente is not None else ""
    dati = {"team": s["slug"], "team_version": versione, "weeks": settimane,
            "company": {"name": azienda.nome, "vat": azienda.partita_iva,
                        "email": getattr(utente, "email", "") or azienda.email, "contact": contatto},
            "plugin": {"kind": "django", "saas": "adabox", "version": operazioni.versione(), "base_url": base,
                       "operations": [e.dichiarazione() for e in operazioni.esposte()]}}
    if note:
        dati["notes"] = note
    agate = _agate()
    if agate:
        dati["agate"] = agate
    stato, corpo = richiesta("POST", "/api/hire-requests", forge_url=forge, dati=dati)
    if stato in (404, 409):
        dimentica_catalogo(forge, s["reparto"])
        raise ErroreFabbrica("squadra sconosciuta o non più in catalogo" if stato == 404 else
                             "la squadra è cambiata nel frattempo: rileggi il catalogo e richiedila di nuovo", stato)
    if stato == 422:
        raise ErroreFabbrica(f"la fabbrica ha rifiutato i dati{_dettaglio(corpo)}", stato)
    if stato == 429:
        raise ErroreFabbrica("troppe richieste: la fabbrica ne accetta al massimo 10 l'ora, riprova più tardi", stato)
    if stato != 201:
        raise ErroreFabbrica(f"risposta inattesa della fabbrica (HTTP {stato})", stato)
    request_id, token = corpo.get("request_id"), corpo.get("token")
    if not isinstance(request_id, str) or not REQUEST_ID_RE.match(request_id):
        raise ErroreFabbrica("la fabbrica non ha restituito l'id della richiesta", stato)
    if not isinstance(token, str) or not token.startswith("wfr_"):
        raise ErroreFabbrica("la fabbrica non ha restituito un token valido", stato)
    r = RichiestaAgenti.objects.create(
        request_id=request_id, forge_url=forge, base_url=base, team_slug=s["slug"], team_nome=s["nome"],
        team_versione=versione, reparto=s["reparto"], settimane=settimane, note=note,
        stato=STATI_RICHIESTA.get(corpo.get("status"), RichiestaAgenti.INVIATA),
        token_cifrato=cifratura.cifra(token), operazioni=s["operazioni"], prezzo=s["prezzo"], azienda=azienda,
        creata_da=utente if getattr(utente, "pk", None) else None)
    log.info("richiesta d'ingaggio %s inviata (squadra %s)", request_id, s["slug"])
    return r


def _percorso(r):
    return f"/api/hire-requests/{quote(r.request_id, safe='')}"


def aggiorna(r):
    """Lo stato della richiesta (§7.3). Alla prima lettura `connected` arriva il token della fabbrica e adabox si
    collega da solo, come con il codice `wfc_...`; il bearer MCP no: lo genera una persona, che deve vederlo.
    Quando il contratto è proposto (§8.3) adabox lo confronta con quello che la persona ha confermato e, se
    combacia, lo approva a suo nome (`contratto.automatico`)."""
    if not r.aperta:
        return r
    stato, corpo = richiesta("GET", _percorso(r), forge_url=r.forge_url, token=r.token())
    if stato in (401, 404):
        raise ErroreFabbrica("la fabbrica non riconosce più questa richiesta", stato)
    if stato != 200:
        raise ErroreFabbrica(f"risposta inattesa della fabbrica (HTTP {stato})", stato)
    nuovo = STATI_RICHIESTA.get(corpo.get("status"))
    if nuovo is None:
        raise ErroreFabbrica("stato della richiesta sconosciuto", stato)
    adesso = timezone.now()
    campi = {"messaggio": _testo(corpo.get("message"), 2000), "letta_il": adesso, "aggiornata": adesso}
    url = corpo.get("approve_url")
    if isinstance(url, str) and url.startswith(("https://", "http://")) and len(url) <= 500:
        campi["approve_url"] = url
    approval_id, proposta = corpo.get("approval_id"), corpo.get("proposal")
    if nuovo == RichiestaAgenti.DA_APPROVARE and isinstance(approval_id, str) and REQUEST_ID_RE.match(approval_id)             and isinstance(proposta, dict):
        campi["approval_id"], campi["proposta"] = approval_id, proposta     # §8.3: da confrontare con il consenso
        if approval_id != r.approval_id:                                   # un contratto nuovo: si decide di nuovo
            campi.update(decisione="", decisione_il=None, decisione_msg="")
    token = corpo.get("plugin_token")
    righe = RichiestaAgenti.objects.filter(pk=r.pk)
    if nuovo == RichiestaAgenti.COLLEGATA and isinstance(token, str) and token.startswith("wpt_"):
        completa(r.forge_url, r.base_url or Collegamento.attuale().base_url, token, corpo.get("install_id"),
                 corpo.get("engagement"), operazioni.versione(), r.azienda, tieni_bearer=True,
                 dopo_il_salvataggio=lambda c: righe.update(stato=nuovo, collegata_il=adesso, **campi))
        log.info("richiesta d'ingaggio %s approvata: collegato", r.request_id)
    else:
        if nuovo == RichiestaAgenti.COLLEGATA and not campi["messaggio"]:
            campi["messaggio"] = ("Approvata, ma il collegamento non è arrivato fin qui: chiedi ad Agentlia un codice "
                                  "di collegamento e usalo in Agenti AI → Avanzate → Stato e collegamento.")
        righe.filter(collegata_il__isnull=True).update(stato=nuovo, **campi)    # mai indietro da collegata
    r.refresh_from_db()
    from . import contratto
    return contratto.automatico(r)


def aggiorna_aperte(piu_vecchie_di=0):
    """Legge lo stato delle richieste aperte (lette più di `piu_vecchie_di` secondi fa). Restituisce gli errori."""
    aperte = RichiestaAgenti.objects.filter(stato__in=RichiestaAgenti.APERTE)
    if piu_vecchie_di:
        limite = timezone.now() - datetime.timedelta(seconds=piu_vecchie_di)
        aperte = aperte.filter(Q(letta_il__isnull=True) | Q(letta_il__lt=limite))
    errori = []
    for r in aperte:
        try:
            aggiorna(r)
        except ErroreFabbrica as e:
            log.warning("richiesta d'ingaggio %s: %s", r.request_id, e)
            errori.append(f"{r.team_nome or r.team_slug}: {e}")
    return errori


def ritira(r):
    """Ritira la richiesta (§7.3): solo finché la fabbrica non l'ha presa in carico."""
    if r.stato != RichiestaAgenti.INVIATA:
        raise ErroreFabbrica("si ritira solo una richiesta appena inviata: dopo, si rifiuta nella console di Agate")
    stato, _ = richiesta("DELETE", _percorso(r), forge_url=r.forge_url, token=r.token())
    if stato in (200, 204):
        RichiestaAgenti.objects.filter(pk=r.pk).update(stato=RichiestaAgenti.RITIRATA, aggiornata=timezone.now(),
                                                       messaggio="Ritirata da adabox.")
        r.refresh_from_db()
        return r
    if stato == 409:
        raise ErroreFabbrica("la fabbrica l'ha già presa in carico: ora si rifiuta nella console di Agate", stato)
    if stato in (401, 404):
        raise ErroreFabbrica("la fabbrica non riconosce più questa richiesta", stato)
    raise ErroreFabbrica(f"risposta inattesa della fabbrica (HTTP {stato})", stato)
