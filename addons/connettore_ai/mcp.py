"""Il server MCP per le chat esterne: un solo indirizzo, una richiesta JSON-RPC per POST, una risposta JSON.

Parla due «ere» del protocollo sullo stesso indirizzo, perché le chat non sono tutte alla stessa versione:
- moderna (2026-07-28), senza stato: ogni richiesta porta la versione in `_meta` e nelle intestazioni
  (`MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`), che devono coincidere con il corpo; c'è `server/discover`;
- storica (2025-11-25 e precedenti): `initialize`, poi le richieste. Nessuna sessione: non serve.

Autorizzazione: il token di accesso emesso da questa istanza. Senza token valido la risposta è 401 con l'indirizzo dei
metadati della risorsa, da cui la chat parte per farsi autorizzare. GET e DELETE: 405."""
import base64
import binascii
import json
import logging
import time

from django.core.cache import cache
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import catalogo, clienti, oauth, stato

log = logging.getLogger("connettore_ai")

MODERNA = "2026-07-28"
STORICHE = ("2025-11-25", "2025-06-18", "2025-03-26")
SUPPORTATE = [MODERNA, *STORICHE]
META_VERSIONE = "io.modelcontextprotocol/protocolVersion"
META_SERVER = "io.modelcontextprotocol/serverInfo"
MAX_CORPO = 1_000_000
CHIAMATE_AL_MINUTO = 120
DURATA_ELENCO_MS = 300_000
PARSE, NON_VALIDA, METODO_SCONOSCIUTO, PARAMETRI = -32700, -32600, -32601, -32602
INTESTAZIONI, VERSIONE_NON_SUPPORTATA = -32020, -32022


class ErroreRpc(Exception):
    def __init__(self, codice, messaggio, http=200, dati=None):
        super().__init__(messaggio)
        self.codice, self.messaggio, self.http, self.dati = codice, messaggio, http, dati


def _errore(ident, codice, messaggio, dati=None):
    errore = {"code": codice, "message": messaggio}
    if dati is not None:
        errore["data"] = dati
    return {"jsonrpc": "2.0", "id": ident, "error": errore}


def _info():
    from core.registry.modules import manifests_attivi
    manifest = manifests_attivi().get("connettore_ai")
    return {"name": "adabox", "title": "adabox", "version": manifest.version if manifest else "1.0.0"}


# ---------- vista HTTP ----------

def _non_autorizzato(presentato):
    """401 con la sfida da cui la chat scopre dove farsi autorizzare (RFC 9728, RFC 6750)."""
    risposta = JsonResponse({"error": "invalid_token" if presentato else "unauthorized",
                             "error_description": "serve un token di accesso emesso da questa istanza di adabox"}, status=401)
    sfida = f'Bearer resource_metadata="{stato.metadati_risorsa()}", scope="{stato.AMBITO}"'
    risposta["WWW-Authenticate"] = sfida + (', error="invalid_token"' if presentato else "")
    return risposta


def _entro_il_limite(collegamento):
    chiave = f"connettore_ai:{collegamento.pk}:{int(time.time() // 60)}"
    cache.add(chiave, 0, 120)
    try:
        return cache.incr(chiave) <= CHIAMATE_AL_MINUTO
    except ValueError:                                  # voce scaduta tra add e incr
        return True


@csrf_exempt
def mcp(request):
    if stato.spento():
        raise Http404
    if request.method != "POST":
        risposta = JsonResponse(_errore(None, NON_VALIDA, "usare POST: una richiesta JSON-RPC per chiamata"), status=405)
        risposta["Allow"] = "POST"
        return risposta
    origine = request.headers.get("Origin")
    if origine and not clienti.origine_valida(origine):
        return JsonResponse(_errore(None, NON_VALIDA, "intestazione Origin non valida"), status=403)
    schema, _, token = (request.headers.get("Authorization") or "").partition(" ")
    token = token.strip() if schema.lower() == "bearer" else ""
    collegamento = oauth.collegamento_di(token)
    if collegamento is None:
        return _non_autorizzato(bool(token))
    if not _entro_il_limite(collegamento):
        risposta = JsonResponse(_errore(None, NON_VALIDA, "troppe chiamate: riprova tra un minuto"), status=429)
        risposta["Retry-After"] = "60"
        return risposta
    if len(request.body) > MAX_CORPO:
        return JsonResponse(_errore(None, NON_VALIDA, "richiesta troppo grande"), status=413)
    try:
        messaggio = json.loads(request.body)
    except ValueError:
        return JsonResponse(_errore(None, PARSE, "JSON non valido"), status=400)
    if not isinstance(messaggio, dict) or messaggio.get("jsonrpc") != "2.0" or not isinstance(messaggio.get("method"), str):
        return JsonResponse(_errore(None, NON_VALIDA, "serve una richiesta JSON-RPC 2.0 (non un elenco)"), status=400)
    if "id" not in messaggio:                           # notifica (notifications/initialized, cancelled…): niente da dire
        return HttpResponse(status=202)
    catalogo.segna_uso(collegamento)
    ident, parametri = messaggio["id"], messaggio.get("params")
    parametri = parametri if isinstance(parametri, dict) else {}
    moderna = _moderna(request, messaggio["method"], parametri)
    try:
        if moderna:
            _controlla_intestazioni(request, messaggio["method"], parametri)
        risultato = _esegui(collegamento, messaggio["method"], parametri, moderna)
    except ErroreRpc as e:
        return JsonResponse(_errore(ident, e.codice, e.messaggio, e.dati), status=e.http if moderna else 200)
    return JsonResponse({"jsonrpc": "2.0", "id": ident, "result": risultato})


# ---------- le due ere ----------

def _versione_nel_corpo(parametri):
    meta = parametri.get("_meta") if isinstance(parametri.get("_meta"), dict) else {}
    return meta.get(META_VERSIONE)


def _moderna(request, metodo, parametri):
    """True se la richiesta è dell'era senza stato. `initialize` e le versioni storiche dichiarate sono dell'altra;
    senza intestazione e senza versione nel corpo è un client di prima del 2025-06-18."""
    if metodo == "initialize":
        return False
    if metodo == "server/discover":
        return True
    versione = _versione_nel_corpo(parametri) or request.headers.get("MCP-Protocol-Version", "")
    return bool(versione) and versione not in STORICHE


def _nome_da_intestazione(valore):
    """`Mcp-Name` in chiaro, o decodificato se è nella forma =?base64?…?= (nomi non ASCII)."""
    if valore.startswith("=?base64?") and valore.endswith("?="):
        try:
            return base64.b64decode(valore[9:-2], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as e:
            raise ErroreRpc(INTESTAZIONI, "Mcp-Name: codifica non valida", 400) from e
    return valore


def _controlla_intestazioni(request, metodo, parametri):
    """Le intestazioni devono dire le stesse cose del corpo: un proxy che instrada sulle intestazioni e il server che
    esegue sul corpo non possono vedere due richieste diverse."""
    intestazione, nel_corpo = request.headers.get("MCP-Protocol-Version"), _versione_nel_corpo(parametri)
    if not intestazione or intestazione != nel_corpo:
        raise ErroreRpc(INTESTAZIONI, "MCP-Protocol-Version manca o è diversa dalla versione in _meta", 400)
    if intestazione != MODERNA:
        raise ErroreRpc(VERSIONE_NON_SUPPORTATA, "Unsupported protocol version", 400,
                        {"supported": SUPPORTATE, "requested": intestazione})
    if request.headers.get("Mcp-Method") != metodo:
        raise ErroreRpc(INTESTAZIONI, "Mcp-Method manca o è diversa dal metodo nel corpo", 400)
    if metodo == "tools/call" and _nome_da_intestazione(request.headers.get("Mcp-Name", "")) != parametri.get("name"):
        raise ErroreRpc(INTESTAZIONI, "Mcp-Name manca o è diversa dal nome nel corpo", 400)


def _esegui(collegamento, metodo, parametri, moderna):
    if metodo == "tools/list":
        risultato = {"tools": catalogo.elenco(collegamento)}
        if moderna:                                     # l'elenco dipende dai permessi della persona: mai in cache condivise
            risultato.update(ttlMs=DURATA_ELENCO_MS, cacheScope="private")
    elif metodo == "tools/call":
        risultato = _chiama(collegamento, parametri)
    elif metodo == "server/discover" and moderna:
        risultato = {"supportedVersions": SUPPORTATE, "capabilities": {"tools": {"listChanged": False}},
                     "instructions": catalogo.ISTRUZIONI, "ttlMs": DURATA_ELENCO_MS, "cacheScope": "public"}
    elif metodo == "initialize" and not moderna:
        chiesta = str(parametri.get("protocolVersion") or "")
        return {"protocolVersion": chiesta if chiesta in STORICHE else STORICHE[0],
                "capabilities": {"tools": {"listChanged": False}}, "serverInfo": _info(), "instructions": catalogo.ISTRUZIONI}
    elif metodo == "ping" and not moderna:
        return {}
    else:
        raise ErroreRpc(METODO_SCONOSCIUTO, "Method not found", 404)
    if moderna:
        risultato = {"resultType": "complete", **risultato, "_meta": {META_SERVER: _info()}}
    return risultato


def _chiama(collegamento, parametri):
    nome, argomenti = parametri.get("name"), parametri.get("arguments")
    argomenti = {} if argomenti is None else argomenti
    if not isinstance(nome, str) or not isinstance(argomenti, dict):
        raise ErroreRpc(PARAMETRI, "servono name e arguments")
    try:
        esito = catalogo.chiama(collegamento, nome, dict(argomenti))
    except catalogo.Sconosciuto:
        raise ErroreRpc(PARAMETRI, "Unknown tool: strumento sconosciuto o non compreso nel collegamento")
    risultato = {"content": [{"type": "text", "text": esito.testo}], "isError": esito.errore}
    if esito.dati is not None:
        risultato["structuredContent"] = esito.dati
    return risultato
