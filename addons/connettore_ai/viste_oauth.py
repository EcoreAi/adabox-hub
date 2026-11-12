"""Gli indirizzi del server di autorizzazione: metadati, registrazione, autorizzazione con il consenso, token, revoca.

I metadati sono pubblici e stanno agli indirizzi fissati dagli standard (RFC 9728 e RFC 8414), alla radice dell'istanza.
Token, registrazione e revoca non hanno la sessione né il CSRF: li proteggono il codice con PKCE, il segreto del client
quando c'è, e l'elenco degli indirizzi di ritorno ammessi. L'autorizzazione invece è una pagina di adabox: accesso
normale (con la verifica in due passaggi), consenso esplicito, CSRF."""
import base64
import binascii
import json
from functools import wraps
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import clienti, oauth, stato
from .models import FORNITORI

PARAMETRI = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state", "scope", "resource")
MAX_REGISTRAZIONE = 20_000


def _json(dati, status=200, pubblico=False):
    risposta = JsonResponse(dati, status=status)
    if pubblico:                                        # metadati: li leggono anche i client che girano in un browser
        risposta["Access-Control-Allow-Origin"] = "*"
        risposta["Cache-Control"] = "public, max-age=3600"
    else:
        risposta["Cache-Control"] = "no-store"
        risposta["Pragma"] = "no-cache"
    return risposta


def _assoluto(nome):
    return stato.base() + reverse(nome)


def _acceso(vista):
    """404 quando il connettore è spento: gli indirizzi alla radice non passano dai middleware dei moduli."""
    @wraps(vista)
    def avvolta(request, *args, **kwargs):
        if stato.spento():
            raise Http404
        return vista(request, *args, **kwargs)
    return avvolta


# ---------- metadati ----------

@require_GET
@_acceso
def metadati_risorsa(request):
    """RFC 9728: dove farsi autorizzare per usare il server MCP di questa istanza."""
    return _json({"resource": stato.risorsa(), "authorization_servers": [stato.emittente()],
                  "scopes_supported": [stato.AMBITO], "bearer_methods_supported": ["header"], "resource_name": "adabox",
                  "resource_documentation": _assoluto("connettore_ai:mie")}, pubblico=True)


@require_GET
@_acceso
def metadati_server(request):
    """RFC 8414. Senza `code_challenge_methods_supported` le chat si fermano; con `client_id_metadata_document_supported`
    usano il documento pubblico, altrimenti si registrano da sé."""
    metodi = list(clienti.METODI_TOKEN)
    return _json({
        "issuer": stato.emittente(),
        "authorization_endpoint": _assoluto("connettore_ai:autorizza"),
        "token_endpoint": _assoluto("connettore_ai:token"),
        "registration_endpoint": _assoluto("connettore_ai:registra"),
        "revocation_endpoint": _assoluto("connettore_ai:revoca"),
        "response_types_supported": ["code"], "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": metodi, "revocation_endpoint_auth_methods_supported": metodi,
        "scopes_supported": [stato.AMBITO, "offline_access"],     # offline_access: Claude lo chiede per avere il rinnovo
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
    }, pubblico=True)


# ---------- registrazione (DCR) ----------

@csrf_exempt
@require_POST
@_acceso
def registra(request):
    if len(request.body) > MAX_REGISTRAZIONE:
        return _json({"error": "invalid_client_metadata", "error_description": "richiesta troppo grande"}, 400)
    try:
        client, segreto = clienti.registra(json.loads(request.body or b"{}"))
    except ValueError:
        return _json({"error": "invalid_client_metadata", "error_description": "JSON non valido"}, 400)
    except clienti.ClientNonValido as e:
        return _json({"error": e.codice, "error_description": e.descrizione}, 429 if e.codice == "temporarily_unavailable" else 400)
    risposta = {"client_id": client.client_id, "client_id_issued_at": int(client.creato.timestamp()),
                "client_name": client.nome, "redirect_uris": client.redirect_uris,
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
                "token_endpoint_auth_method": client.autenticazione}
    if segreto:
        risposta.update(client_secret=segreto, client_secret_expires_at=0)
    return _json(risposta, 201)


# ---------- autorizzazione e consenso ----------

def _ritorno(uri, **parametri):
    """Il ritorno alla chat con l'esito, sempre con `iss` (RFC 9207): la chat controlla che sia questa istanza."""
    parti = urlsplit(uri)
    query = parse_qsl(parti.query, keep_blank_values=True) + [(k, v) for k, v in parametri.items() if v] \
        + [("iss", stato.emittente())]
    risposta = HttpResponseRedirect(urlunsplit(parti._replace(query=urlencode(query))))
    risposta["Cache-Control"], risposta["Referrer-Policy"] = "no-store", "no-referrer"
    return risposta


def _app_scelte(request):
    """Gli slug da salvare: vuoto = tutte le app che la persona vede; altrimenti quelle spuntate, tra le sue."""
    from core.registry import modules
    visibili = [a for a in modules.app_visibili(request.user) if a["slug"] not in ("ai", "connettore_ai")]
    if request.POST.get("quali") != "alcune":
        return visibili, []
    spuntate = set(request.POST.getlist("app"))
    return visibili, sorted(a["slug"] for a in visibili if a["slug"] in spuntate)


@never_cache
@require_http_methods(["GET", "POST"])
@_acceso
def autorizza(request):
    p = request.POST if request.method == "POST" else request.GET
    # prima l'accesso, poi la richiesta: leggere il documento pubblico di un client è una chiamata di rete, e un
    # visitatore anonimo non deve poterne far partire verso indirizzi scelti da lui
    if not request.user.is_authenticated:
        return redirect_to_login(request.path + "?" + urlencode([(k, p[k]) for k in PARAMETRI if k in p]))
    try:
        richiesta = oauth.leggi_richiesta(p)
    except clienti.ClientNonValido as e:
        return render(request, "connettore_ai/errore.html", {"motivo": e.descrizione}, status=400)
    except oauth.ErroreOAuth as e:
        return _ritorno(e.richiesta.redirect_uri, error=e.codice, error_description=e.descrizione, state=e.richiesta.stato)
    fornitore = clienti.fornitore_di(richiesta.redirect_uri)
    contesto = {"richiesta": richiesta, "fornitore": dict(FORNITORI).get(fornitore, "una chat esterna"),
                "nome_client": richiesta.client.nome, "nascosti": [(k, p[k]) for k in PARAMETRI if k in p],
                "locale": fornitore == "locale"}
    aziende = stato.aziende_collegabili(request.user)
    if not aziende:
        motivo = ("La tua azienda non ha acceso il collegamento alle chat AI esterne: chiedilo a un amministratore."
                  if stato.puo_collegare(request.user) else "Il tuo utente non può collegare adabox alle chat AI esterne.")
        return render(request, "connettore_ai/errore.html", {**contesto, "motivo": motivo, "negato": True}, status=403)
    visibili, app = _app_scelte(request)
    contesto.update(aziende=aziende, app_visibili=visibili, azienda_scelta=str(getattr(getattr(request, "azienda", None), "pk", "")))
    if request.method == "POST":
        if "consenti" not in request.POST:
            return _ritorno(richiesta.redirect_uri, error="access_denied",
                            error_description="la persona non ha dato il consenso", state=richiesta.stato)
        azienda = next((a for a in aziende if str(a.pk) == request.POST.get("azienda")), aziende[0] if len(aziende) == 1 else None)
        if azienda is None:
            contesto["errore"] = "Scegli l'azienda da collegare."
        elif request.POST.get("quali") == "alcune" and not app:
            contesto["errore"] = "Scegli almeno un'app, oppure «tutte»."
        else:
            return _ritorno(richiesta.redirect_uri, code=oauth.emetti_codice(richiesta, request.user, azienda, app),
                            state=richiesta.stato)
    return render(request, "connettore_ai/consenso.html", contesto)


# ---------- token e revoca ----------

def _basic(request):
    """(client_id, segreto) dall'intestazione Basic, None se non c'è."""
    schema, _, valore = (request.headers.get("Authorization") or "").partition(" ")
    if schema.lower() != "basic":
        return None
    try:
        nome, _, segreto = base64.b64decode(valore.strip(), validate=True).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return "", ""
    return unquote(nome), unquote(segreto)


def _errore_oauth(e):
    risposta = _json({"error": e.codice, "error_description": e.descrizione}, e.stato_http)
    if e.stato_http == 401:
        risposta["WWW-Authenticate"] = 'Basic realm="adabox"'
    return risposta


@csrf_exempt
@require_POST
@_acceso
def token(request):
    try:
        return _json(oauth.emetti(request.POST, _basic(request)))
    except oauth.ErroreOAuth as e:
        return _errore_oauth(e)


@csrf_exempt
@require_POST
@_acceso
def revoca(request):
    try:
        oauth.revoca_token(request.POST, _basic(request))
    except oauth.ErroreOAuth as e:
        return _errore_oauth(e)
    return _json({})
