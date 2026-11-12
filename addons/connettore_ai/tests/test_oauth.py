import base64
import json
from datetime import timedelta

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone

from connettore_ai import oauth, stato
from connettore_ai.models import ChatCollegata, ClientOAuth, Codice, Token
from core import parametri

from .conftest import (CHATGPT, CLAUDE, DOCUMENTO_CHATGPT, DOCUMENTO_CLAUDE, MCP, SITO, consenti, persona, richiesta,
                       rinnova, ritorno_di, rpc, scambia, serve_contatti)

GEMINI_APP = [f"https://oauth-redirect{v}.googleusercontent.com/{p}/user_bound_custom-mcp-1234-adabox"
              for v in ("", "-sandbox", "-test") for p in ("r", "a")]
GEMINI_ENTERPRISE = "https://vertexaisearch.cloud.google.com/oauth-redirect"
MISTRAL = "https://callback.mistral.ai/v1/integrations_auth/oauth2_callback"


def registra(client, **dati):
    return client.post("/connettore_ai/oauth/register", json.dumps(dati), content_type="application/json")


# ---------- metadati ----------

def test_metadati_della_risorsa_e_del_server(client, azienda):
    for percorso in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource"):
        risorsa = client.get(percorso)
        assert risorsa.status_code == 200 and risorsa["Access-Control-Allow-Origin"] == "*"
        assert risorsa.json()["resource"] == MCP and risorsa.json()["authorization_servers"] == [SITO]
    server = client.get("/.well-known/oauth-authorization-server").json()
    assert server["issuer"] == SITO
    assert server["authorization_endpoint"] == SITO + "/connettore_ai/oauth/authorize"
    assert server["token_endpoint"] == SITO + "/connettore_ai/oauth/token"
    assert server["registration_endpoint"] == SITO + "/connettore_ai/oauth/register"
    assert server["code_challenge_methods_supported"] == ["S256"]                   # senza, le chat si fermano
    assert "none" in server["token_endpoint_auth_methods_supported"]                # Claude sceglie il documento pubblico
    assert server["client_id_metadata_document_supported"] is True
    assert server["authorization_response_iss_parameter_supported"] is True         # ChatGPT usa il ritorno stabile
    assert "offline_access" in server["scopes_supported"]


def test_modulo_spento_niente_risponde(client, azienda, monkeypatch):
    monkeypatch.setattr(stato, "spento", lambda: True)
    for percorso in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-authorization-server"):
        assert client.get(percorso).status_code == 404
    assert client.post("/mcp", {}, content_type="application/json").status_code == 404
    assert client.post("/connettore_ai/oauth/token", {}).status_code == 404
    assert registra(client, redirect_uris=[CLAUDE]).status_code == 404


# ---------- il giro completo, come lo fa ogni fornitore ----------

def test_chatgpt_con_il_documento_pubblico(client, mario, documenti):
    """ChatGPT dichiara private_key_jwt ma accetta «none»: per noi è un client pubblico con PKCE."""
    anonimo = client.get("/connettore_ai/oauth/authorize", richiesta(DOCUMENTO_CHATGPT, CHATGPT))
    assert anonimo.status_code == 302 and anonimo["Location"].startswith("/accounts/login/?next=")
    assert "code_challenge" in anonimo["Location"] and not ClientOAuth.objects.exists()    # senza accesso non si legge nessun documento
    client.force_login(mario)
    pagina = client.get("/connettore_ai/oauth/authorize", richiesta(DOCUMENTO_CHATGPT, CHATGPT))
    html = pagina.content.decode()
    assert pagina.status_code == 200 and "Collegare ChatGPT ad adabox?" in html and "Consenti solo se hai avviato tu" in html
    assert 'name="code_challenge"' in html and pagina["Cache-Control"].startswith("max-age=0")
    codice = consenti(client, mario, DOCUMENTO_CHATGPT, CHATGPT)
    risposta = scambia(client, DOCUMENTO_CHATGPT, CHATGPT, codice)
    token = risposta.json()
    assert risposta.status_code == 200 and risposta["Cache-Control"] == "no-store"
    assert token["token_type"] == "Bearer" and token["expires_in"] == 3600 and token["scope"] == "adabox:leggi"
    collegamento = ChatCollegata.objects.get()
    assert (collegamento.utente, collegamento.fornitore, collegamento.app, collegamento.sola_lettura) == (mario, "chatgpt", [], True)
    assert ClientOAuth.objects.get().tipo == ClientOAuth.CIMD
    assert not Token.objects.filter(impronta__in=[token["access_token"], token["refresh_token"]]).exists()   # solo impronte
    assert rpc(client, token["access_token"], "tools/list").status_code == 200


def test_claude_che_si_registra_da_se(client, mario):
    """Senza documento pubblico Claude si registra a ogni collegamento, come client pubblico."""
    r = registra(client, client_name="Claude", redirect_uris=[CLAUDE], token_endpoint_auth_method="none",
                 grant_types=["authorization_code", "refresh_token"], response_types=["code"])
    dati = r.json()
    assert r.status_code == 201 and dati["client_id"].startswith("cai_c_") and "client_secret" not in dati
    codice = consenti(client, mario, dati["client_id"], CLAUDE)
    assert scambia(client, dati["client_id"], CLAUDE, codice).status_code == 200
    assert ChatCollegata.objects.get().fornitore == "claude"


def test_app_gemini_sei_ritorni_e_segreto_nel_corpo(client, mario):
    """L'app Gemini si registra con sei indirizzi e client_secret_post, e non vuole che il rinnovo cambi."""
    r = registra(client, client_name="Google", redirect_uris=GEMINI_APP, token_endpoint_auth_method="client_secret_post",
                 grant_types=["authorization_code", "refresh_token"])
    dati = r.json()
    assert r.status_code == 201 and dati["client_secret_expires_at"] == 0 and len(dati["redirect_uris"]) == 6
    codice = consenti(client, mario, dati["client_id"], GEMINI_APP[0])
    assert scambia(client, dati["client_id"], GEMINI_APP[0], codice).status_code == 401            # senza segreto
    assert Codice.objects.get().usato is None                                                    # il codice non si brucia
    token = scambia(client, dati["client_id"], GEMINI_APP[0], codice, client_secret=dati["client_secret"]).json()
    assert ChatCollegata.objects.get().fornitore == "gemini"
    rinnovato = rinnova(client, dati["client_id"], token["refresh_token"], client_secret=dati["client_secret"]).json()
    assert rinnovato["refresh_token"] == token["refresh_token"] and rinnovato["access_token"] != token["access_token"]
    assert rinnova(client, dati["client_id"], token["refresh_token"], client_secret=dati["client_secret"]).status_code == 200


def test_le_chat_si_registra_con_il_suo_ritorno(client, mario):
    dati = registra(client, client_name="Le Chat", redirect_uris=[MISTRAL]).json()
    codice = consenti(client, mario, dati["client_id"], MISTRAL)
    assert scambia(client, dati["client_id"], MISTRAL, codice).status_code == 200
    assert ChatCollegata.objects.get().fornitore == "mistral"


def test_gemini_enterprise_con_le_credenziali_create_a_mano(client, mario, azienda):
    """Un amministratore crea identificativo e segreto; Google li presenta con Basic e non manda `resource`."""
    admin = persona("admin", azienda, "add_clientoauth")
    client.force_login(mario)
    assert client.get("/connettore_ai/credenziali/").status_code == 403
    client.force_login(admin)
    assert "Client secret" not in client.get("/connettore_ai/credenziali/").content.decode()
    html = client.post("/connettore_ai/credenziali/").content.decode()
    creato = ClientOAuth.objects.get()
    assert creato.tipo == ClientOAuth.A_MANO and creato.redirect_uris == [GEMINI_ENTERPRISE] and creato.client_id in html
    segreto = html.split('value="cai_s_')[1].split('"')[0]
    assert oauth.impronta("cai_s_" + segreto) == creato.impronta and "cai_s_" + segreto not in creato.impronta
    client.logout()
    client.force_login(mario)
    senza_risorsa = {k: v for k, v in richiesta(creato.client_id, GEMINI_ENTERPRISE).items() if k != "resource"}
    _, parametri_ritorno = ritorno_di(client.post("/connettore_ai/oauth/authorize", {**senza_risorsa, "consenti": "1", "quali": "tutte"}))
    client.logout()
    basic = "Basic " + base64.b64encode(f"{creato.client_id}:cai_s_{segreto}".encode()).decode()
    corpo = f"grant_type=authorization_code&code={parametri_ritorno['code']}&redirect_uri={GEMINI_ENTERPRISE}&code_verifier={'v' * 64}"
    sbagliato = client.post("/connettore_ai/oauth/token", corpo, content_type="application/x-www-form-urlencoded",
                            HTTP_AUTHORIZATION="Basic " + base64.b64encode(f"{creato.client_id}:no".encode()).decode())
    assert sbagliato.status_code == 401 and sbagliato.json()["error"] == "invalid_client"
    giusto = client.post("/connettore_ai/oauth/token", corpo, content_type="application/x-www-form-urlencoded", HTTP_AUTHORIZATION=basic)
    assert giusto.status_code == 200 and ChatCollegata.objects.get().fornitore == "gemini"


# ---------- che cosa non passa ----------

def test_registrazione_rifiuta_i_ritorni_fuori_elenco(client, azienda):
    for ritorni in ([], ["https://malintenzionato.example/callback"], [CLAUDE, "https://altro.example/cb"],
                    ["http://claude.ai/api/mcp/auth_callback"], ["https://chatgpt.com/connector/oauth/"],
                    ["https://oauth-redirect.googleusercontent.com/r/progetto-di-un-altro"], [CLAUDE + "#frammento"]):
        r = registra(client, redirect_uris=ritorni)
        assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri", ritorni
    assert registra(client, redirect_uris=[CLAUDE], token_endpoint_auth_method="private_key_jwt").json()["error"] == "invalid_client_metadata"
    assert registra(client, redirect_uris=[CLAUDE], grant_types=["client_credentials"]).status_code == 400
    assert not ClientOAuth.objects.exists()
    assert registra(client, redirect_uris=["https://chatgpt.com/connector/oauth/abc123"]).status_code == 201


def test_ritorni_aggiunti_a_mano_e_programmi_locali(client, azienda):
    assert registra(client, redirect_uris=["http://127.0.0.1:47823/callback"]).status_code == 400
    assert registra(client, redirect_uris=["https://chat.cliente.it/oauth/cb"]).status_code == 400
    parametri.scrivi("connettore_ai.client_locali", True)
    parametri.scrivi("connettore_ai.ritorni_extra", "https://chat.cliente.it/oauth/cb https://altra.example/x/*")
    assert registra(client, redirect_uris=["http://127.0.0.1:47823/callback"]).status_code == 201
    assert registra(client, redirect_uris=["https://chat.cliente.it/oauth/cb"]).status_code == 201
    assert registra(client, redirect_uris=["https://altra.example/x/abc"]).status_code == 201
    assert registra(client, redirect_uris=["https://chat.cliente.it/oauth/altro"]).status_code == 400


def test_programma_locale_la_porta_cambia(client, mario, documenti):
    """Claude Code dichiara http://localhost/callback senza porta e ogni volta ne usa una diversa."""
    codice_claude = "https://claude.ai/oauth/claude-code-client-metadata"
    documenti[codice_claude] = {"client_id": codice_claude, "client_name": "Claude Code",
                                "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"]}
    client.force_login(mario)
    spento = client.get("/connettore_ai/oauth/authorize", richiesta(codice_claude, "http://localhost:51234/callback"))
    assert spento.status_code == 400 and "non riuscito" in spento.content.decode()
    parametri.scrivi("connettore_ai.client_locali", True)
    pagina = client.get("/connettore_ai/oauth/authorize", richiesta(codice_claude, "http://localhost:51234/callback"))
    assert pagina.status_code == 200 and "programma sul tuo computer" in pagina.content.decode()
    assert client.get("/connettore_ai/oauth/authorize", richiesta(codice_claude, "http://localhost:51234/altro")).status_code == 400
    codice = consenti(client, mario, codice_claude, "http://localhost:51234/callback")
    assert scambia(client, codice_claude, "http://localhost:51234/callback", codice).status_code == 200
    assert ChatCollegata.objects.get().fornitore == "locale"


def test_documento_pubblico_non_valido(client, mario, documenti):
    client.force_login(mario)
    documenti["https://chatgpt.com/oauth/altro.json"] = {"client_id": DOCUMENTO_CHATGPT, "redirect_uris": [CHATGPT]}
    documenti["https://finto.example/client.json"] = {"client_id": "https://finto.example/client.json",
                                                      "redirect_uris": ["https://finto.example/cb"]}
    documenti["https://chatgpt.com/oauth/segreto.json"] = {"client_id": "https://chatgpt.com/oauth/segreto.json",
                                                           "redirect_uris": [CHATGPT], "token_endpoint_auth_method": "private_key_jwt"}
    for client_id, ritorno in (("https://chatgpt.com/oauth/altro.json", CHATGPT),        # dichiara un altro client_id
                               ("https://finto.example/client.json", "https://finto.example/cb"),   # ritorno fuori elenco
                               ("https://chatgpt.com/oauth/segreto.json", CHATGPT),      # non sa fare da client pubblico
                               ("https://nessuno.example/client.json", CHATGPT),         # documento che non c'è
                               ("https://chatgpt.com", CHATGPT),                         # senza percorso
                               ("sconosciuto", CHATGPT)):
        r = client.get("/connettore_ai/oauth/authorize", richiesta(client_id, ritorno))
        assert r.status_code == 400 and "Location" not in r, client_id                  # mai un reindirizzamento
    assert client.get("/connettore_ai/oauth/authorize", richiesta(DOCUMENTO_CLAUDE, CHATGPT)).status_code == 400   # ritorno di un altro
    assert not Codice.objects.exists()


def test_errori_che_tornano_alla_chat_con_iss(client, mario, documenti):
    client.force_login(mario)
    for cambi, errore in (({"code_challenge": ""}, "invalid_request"), ({"code_challenge_method": "plain"}, "invalid_request"),
                          ({"response_type": "token"}, "unsupported_response_type"),
                          ({"resource": "https://altra-istanza.example/mcp"}, "invalid_target")):
        indirizzo, p = ritorno_di(client.get("/connettore_ai/oauth/authorize", richiesta(DOCUMENTO_CLAUDE, CLAUDE, **cambi)))
        assert (indirizzo, p["error"], p["state"], p["iss"]) == (CLAUDE, errore, "st4to", SITO) and "code" not in p
    for risorsa in (MCP + "/", "HTTPS://Hub.Esempio.IT/mcp"):                           # la stessa risorsa scritta in altro modo
        assert client.get("/connettore_ai/oauth/authorize", richiesta(DOCUMENTO_CLAUDE, CLAUDE, resource=risorsa)).status_code == 200
    indirizzo, p = ritorno_di(client.post("/connettore_ai/oauth/authorize", {**richiesta(DOCUMENTO_CLAUDE, CLAUDE), "nega": "1"}))
    assert (p["error"], p["iss"]) == ("access_denied", SITO) and not Codice.objects.exists()


def test_chi_non_puo_collegare(client, azienda, documenti):
    senza_permesso = persona("luca", azienda)
    senza_permesso.user_permissions.clear()
    client.force_login(senza_permesso)
    r = client.get("/connettore_ai/oauth/authorize", richiesta(DOCUMENTO_CLAUDE, CLAUDE))
    assert r.status_code == 403 and "non può collegare" in r.content.decode()
    mario = persona("mario", azienda)
    parametri.scrivi("connettore_ai.attivo", False, azienda)
    client.force_login(mario)
    r = client.get("/connettore_ai/oauth/authorize", richiesta(DOCUMENTO_CLAUDE, CLAUDE))
    assert r.status_code == 403 and "non ha acceso" in r.content.decode()
    assert client.post("/connettore_ai/oauth/authorize", {**richiesta(DOCUMENTO_CLAUDE, CLAUDE), "consenti": "1"}).status_code == 403
    assert not Codice.objects.exists()


def test_consenso_senza_csrf_non_vale(mario, documenti):
    from django.test import Client
    severo = Client(enforce_csrf_checks=True)
    severo.force_login(mario)
    assert severo.post("/connettore_ai/oauth/authorize", {**richiesta(DOCUMENTO_CLAUDE, CLAUDE), "consenti": "1"}).status_code == 403
    assert not Codice.objects.exists()


@serve_contatti
def test_scelta_dell_azienda_e_delle_app(client, mario, documenti, azienda):
    from core.models import Azienda
    altra = Azienda.objects.create(nome="Beta Srl")
    spenta = Azienda.objects.create(nome="Gamma Srl")
    mario.profilo.aziende.add(altra, spenta)
    parametri.scrivi("connettore_ai.attivo", True, altra)
    mario.user_permissions.add(*Permission.objects.filter(codename__in=["view_opportunita"]))
    client.force_login(mario)
    html = client.get("/connettore_ai/oauth/authorize", richiesta(DOCUMENTO_CLAUDE, CLAUDE)).content.decode()
    assert "Beta Srl" in html and "Gamma Srl" not in html and 'value="contatti"' in html and 'value="ai"' not in html
    base = {**richiesta(DOCUMENTO_CLAUDE, CLAUDE), "consenti": "1"}
    assert "Scegli l&#x27;azienda" in client.post("/connettore_ai/oauth/authorize", {**base, "quali": "tutte"}).content.decode()
    assert client.post("/connettore_ai/oauth/authorize", {**base, "azienda": spenta.pk}).status_code == 200   # non collegabile: si richiede
    senza_app = client.post("/connettore_ai/oauth/authorize", {**base, "azienda": altra.pk, "quali": "alcune"})
    assert "Scegli almeno un&#x27;app" in senza_app.content.decode() and not Codice.objects.exists()
    _, p = ritorno_di(client.post("/connettore_ai/oauth/authorize", {**base, "azienda": altra.pk, "quali": "alcune",
                                                                      "app": ["contatti", "ai", "inventata"]}))
    assert scambia(client, DOCUMENTO_CLAUDE, CLAUDE, p["code"]).status_code == 200
    collegamento = ChatCollegata.objects.get()
    assert collegamento.azienda == altra and collegamento.app == ["contatti"]


# ---------- codice e token ----------

def test_il_codice_vale_una_volta_e_riusato_revoca(client, mario, documenti):
    codice = consenti(client, mario, DOCUMENTO_CLAUDE, CLAUDE)
    token = scambia(client, DOCUMENTO_CLAUDE, CLAUDE, codice).json()
    secondo = scambia(client, DOCUMENTO_CLAUDE, CLAUDE, codice)
    assert secondo.status_code == 400 and secondo.json()["error"] == "invalid_grant"
    assert ChatCollegata.objects.get().revocato is not None and not Token.objects.exists()
    assert rpc(client, token["access_token"], "tools/list").status_code == 401


@pytest.mark.parametrize("cambi", [{"code_verifier": "x" * 64}, {"code_verifier": "corto"}, {"code_verifier": ""},
                                   {"redirect_uri": CHATGPT}, {"resource": "https://altra.example/mcp"}, {"code": "inventato"}])
def test_scambio_rifiutato(client, mario, documenti, cambi):
    codice = consenti(client, mario, DOCUMENTO_CLAUDE, CLAUDE)
    r = scambia(client, DOCUMENTO_CLAUDE, CLAUDE, codice, **cambi)
    assert r.status_code == 400 and r.json()["error"] in ("invalid_grant", "invalid_target")
    assert not ChatCollegata.objects.exists() and not Token.objects.exists()


def test_codice_di_un_altro_client_scaduto_o_di_chi_non_puo_piu(client, mario, documenti):
    codice = consenti(client, mario, DOCUMENTO_CLAUDE, CLAUDE)
    consenti(client, mario, DOCUMENTO_CHATGPT, CHATGPT)                                   # fa conoscere anche ChatGPT
    assert scambia(client, DOCUMENTO_CHATGPT, CLAUDE, codice).json()["error"] == "invalid_grant"
    assert scambia(client, "sconosciuto", CLAUDE, codice).status_code == 401
    Codice.objects.update(scade=timezone.now() - timedelta(seconds=1))
    assert scambia(client, DOCUMENTO_CLAUDE, CLAUDE, codice).json()["error_description"] == "codice scaduto"
    Codice.objects.update(scade=timezone.now() + timedelta(minutes=1))
    mario.is_active = False
    mario.save()
    assert scambia(client, DOCUMENTO_CLAUDE, CLAUDE, codice).json()["error"] == "invalid_grant"
    assert not ChatCollegata.objects.exists()
    assert client.post("/connettore_ai/oauth/token", {"grant_type": "password", "client_id": DOCUMENTO_CLAUDE}).json()["error"] == "unsupported_grant_type"


def test_rinnovo_ruota_e_il_riuso_revoca(client, collegata):
    nuovo = rinnova(client, DOCUMENTO_CLAUDE, collegata["refresh_token"])
    assert nuovo.status_code == 200 and nuovo.json()["refresh_token"] != collegata["refresh_token"]
    assert rpc(client, nuovo.json()["access_token"], "tools/list").status_code == 200
    assert rpc(client, collegata["access_token"], "tools/list").status_code == 200          # quello di prima vale fino alla scadenza
    # la risposta si è persa e la chat riprova subito con lo stesso token: va bene
    assert rinnova(client, DOCUMENTO_CLAUDE, collegata["refresh_token"]).status_code == 200
    # lo stesso token ricompare dopo la finestra di grazia: è una copia, si revoca tutto
    Token.objects.filter(usato__isnull=False).update(usato=timezone.now() - timedelta(minutes=5))
    riuso = rinnova(client, DOCUMENTO_CLAUDE, collegata["refresh_token"])
    assert riuso.status_code == 400 and riuso.json()["error"] == "invalid_grant"
    assert ChatCollegata.objects.get().revocato is not None
    assert rinnova(client, DOCUMENTO_CLAUDE, nuovo.json()["refresh_token"]).status_code == 400
    assert rpc(client, nuovo.json()["access_token"], "tools/list").status_code == 401


def test_rinnovo_di_un_altro_client_o_scaduto(client, collegata, mario, documenti):
    consenti(client, mario, DOCUMENTO_CHATGPT, CHATGPT)
    assert rinnova(client, DOCUMENTO_CHATGPT, collegata["refresh_token"]).json()["error"] == "invalid_grant"
    assert rinnova(client, DOCUMENTO_CLAUDE, collegata["access_token"]).json()["error"] == "invalid_grant"    # non è di rinnovo
    Token.objects.filter(tipo=Token.RINNOVO).update(scade=timezone.now() - timedelta(seconds=1))
    assert rinnova(client, DOCUMENTO_CLAUDE, collegata["refresh_token"]).json()["error"] == "invalid_grant"


def test_revoca_dal_client(client, collegata):
    r = client.post("/connettore_ai/oauth/revoke", {"token": "inventato", "client_id": DOCUMENTO_CLAUDE})
    assert r.status_code == 200 and ChatCollegata.objects.get().attivo
    assert client.post("/connettore_ai/oauth/revoke", {"token": collegata["refresh_token"], "client_id": DOCUMENTO_CLAUDE}).status_code == 200
    assert not ChatCollegata.objects.get().attivo
    assert rpc(client, collegata["access_token"], "tools/list").status_code == 401
    assert rinnova(client, DOCUMENTO_CLAUDE, collegata["refresh_token"]).status_code == 400


def test_troppe_registrazioni(client, azienda, monkeypatch):
    from connettore_ai import clienti
    monkeypatch.setattr(clienti, "REGISTRAZIONI_ORA", 2)
    assert [registra(client, redirect_uris=[CLAUDE]).status_code for _ in range(3)] == [201, 201, 429]
