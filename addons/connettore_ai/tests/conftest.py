"""Aiuti dei test del connettore: un'istanza con indirizzo pubblico, una persona che può collegarsi e una chat finta
che fa i passi che farebbero Claude, ChatGPT, Gemini e Le Chat."""
import base64
import hashlib
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission, User

from connettore_ai import clienti
from core import parametri
from core.models import Azienda

SITO = "https://hub.esempio.it"
MCP = SITO + "/mcp"
CLAUDE = "https://claude.ai/api/mcp/auth_callback"
CHATGPT = "https://chatgpt.com/connector_platform_oauth_redirect"
VERIFICATORE = "v" * 64
SFIDA = base64.urlsafe_b64encode(hashlib.sha256(VERIFICATORE.encode()).digest()).rstrip(b"=").decode()
DOCUMENTO_CHATGPT = "https://chatgpt.com/oauth/client.json"
DOCUMENTO_CLAUDE = "https://claude.ai/oauth/mcp-oauth-client-metadata"
# i test sui dati leggono i contatti: nel collaudo del solo modulo (con l'assistente e basta) si saltano
serve_contatti = pytest.mark.skipif(not apps.is_installed("contatti"), reason="serve contatti")


@pytest.fixture(autouse=True)
def istanza_pubblica(settings):
    settings.SITO_URL = SITO
    from django.core.cache import cache
    cache.clear()


@pytest.fixture
def azienda(db):
    a = Azienda.objects.first()
    parametri.scrivi("connettore_ai.attivo", True, a)
    return a


def persona(nome, azienda, *permessi):
    u = User.objects.create_user(nome, f"{nome}@example.com", "pass12345!", first_name=nome.title())
    u.user_permissions.set(Permission.objects.filter(codename__in=["add_chatcollegata", *permessi]))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def mario(azienda):
    return persona("mario", azienda, "view_contatto")


@pytest.fixture
def contatti(azienda):
    from contatti.models import Contatto
    return [Contatto.objects.create(azienda=azienda, nome="Rossi Srl", citta="Cagliari", cliente=True),
            Contatto.objects.create(azienda=azienda, nome="Bianchi Spa", citta="Sassari")]


@pytest.fixture
def documenti(monkeypatch):
    """I documenti pubblici dei client (CIMD), come li servono i fornitori: {indirizzo: contenuto}."""
    pubblicati = {
        DOCUMENTO_CHATGPT: {"client_id": DOCUMENTO_CHATGPT, "client_name": "ChatGPT", "redirect_uris": [CHATGPT],
                            "token_endpoint_auth_method": "private_key_jwt",
                            "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"]},
        DOCUMENTO_CLAUDE: {"client_id": DOCUMENTO_CLAUDE, "client_name": "Claude", "redirect_uris": [CLAUDE],
                           "token_endpoint_auth_method": "none",
                           "grant_types": ["authorization_code", "refresh_token"]},
    }

    def scarica(url):
        if url not in pubblicati:
            raise clienti.ClientNonValido("documento del client non raggiungibile")
        return pubblicati[url]
    monkeypatch.setattr(clienti, "_scarica_documento", scarica)
    return pubblicati


def richiesta(client_id, ritorno, **altri):
    return {"response_type": "code", "client_id": client_id, "redirect_uri": ritorno, "code_challenge": SFIDA,
            "code_challenge_method": "S256", "state": "st4to", "scope": "adabox:leggi", "resource": MCP, **altri}


def ritorno_di(risposta):
    """(indirizzo senza parametri, parametri) del reindirizzamento verso la chat."""
    assert risposta.status_code == 302, risposta.content[:300]
    parti = urlsplit(risposta["Location"])
    return f"{parti.scheme}://{parti.netloc}{parti.path}", {k: v[0] for k, v in parse_qs(parti.query).items()}


def consenti(client, utente, client_id, ritorno, **scelte):
    """La persona accede e dà il consenso: restituisce il codice arrivato alla chat."""
    client.force_login(utente)
    dati = {**richiesta(client_id, ritorno), "consenti": "1", "quali": "tutte", **scelte}
    indirizzo, parametri_ritorno = ritorno_di(client.post("/connettore_ai/oauth/authorize", dati))
    assert indirizzo == ritorno and parametri_ritorno["state"] == "st4to" and parametri_ritorno["iss"] == SITO
    client.logout()
    return parametri_ritorno["code"]


def scambia(client, client_id, ritorno, codice, **altri):
    return client.post("/connettore_ai/oauth/token", urlencode({
        "grant_type": "authorization_code", "code": codice, "redirect_uri": ritorno, "client_id": client_id,
        "code_verifier": VERIFICATORE, "resource": MCP, **altri}), content_type="application/x-www-form-urlencoded")


def rinnova(client, client_id, token, **altri):
    return client.post("/connettore_ai/oauth/token", urlencode({
        "grant_type": "refresh_token", "refresh_token": token, "client_id": client_id, **altri}),
        content_type="application/x-www-form-urlencoded")


@pytest.fixture
def collegata(client, mario, documenti):
    """Mario ha collegato Claude: i token della risposta."""
    codice = consenti(client, mario, DOCUMENTO_CLAUDE, CLAUDE)
    return scambia(client, DOCUMENTO_CLAUDE, CLAUDE, codice).json()


def rpc(client, token, metodo, params=None, ident=1, moderna=False, intestazioni=None):
    """Una richiesta al server MCP. `moderna`: con la versione 2026-07-28 in `_meta` e nelle intestazioni."""
    params = dict(params or {})
    extra = {}
    if moderna:
        params["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                           "io.modelcontextprotocol/clientInfo": {"name": "prova", "version": "1"},
                           "io.modelcontextprotocol/clientCapabilities": {}}
        extra = {"HTTP_MCP_PROTOCOL_VERSION": "2026-07-28", "HTTP_MCP_METHOD": metodo}
        if metodo == "tools/call":
            extra["HTTP_MCP_NAME"] = params.get("name", "")
    corpo = {"jsonrpc": "2.0", "method": metodo, "params": params}
    if ident is not None:
        corpo["id"] = ident
    if token:
        extra["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client.post("/mcp", corpo, content_type="application/json", **{**extra, **(intestazioni or {})})


def chiama(client, token, nome, argomenti=None, moderna=False):
    r = rpc(client, token, "tools/call", {"name": nome, "arguments": argomenti or {}}, moderna=moderna)
    assert r.status_code == 200, r.content[:300]
    return r.json()["result"]
