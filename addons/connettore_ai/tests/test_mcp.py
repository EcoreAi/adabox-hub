import base64
import json

import pytest
from django.contrib.auth.models import Permission

from connettore_ai import mcp, protezione
from connettore_ai.models import ChatCollegata, Chiamata
from core import parametri
from core.models import Azienda

from .conftest import CLAUDE, DOCUMENTO_CLAUDE, SITO, chiama, consenti, rpc, scambia, serve_contatti

META_VERSIONE = "io.modelcontextprotocol/protocolVersion"


@pytest.fixture
def token(collegata):
    return collegata["access_token"]


# ---------- porta d'ingresso ----------

def test_senza_token_401_con_la_strada_per_autorizzarsi(client, azienda):
    r = rpc(client, None, "tools/list")
    assert r.status_code == 401
    assert r["WWW-Authenticate"] == f'Bearer resource_metadata="{SITO}/.well-known/oauth-protected-resource/mcp", scope="adabox:leggi"'
    sbagliato = rpc(client, "cai_a_inventato", "tools/list")
    assert sbagliato.status_code == 401 and 'error="invalid_token"' in sbagliato["WWW-Authenticate"]
    assert client.post("/mcp/", {}, content_type="application/json").status_code == 401     # anche con la barra finale


def test_solo_post_e_solo_json_rpc(client, token):
    for metodo in (client.get, client.delete):
        r = metodo("/mcp", HTTP_AUTHORIZATION=f"Bearer {token}")
        assert r.status_code == 405 and r["Allow"] == "POST"
    autorizzato = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    assert client.post("/mcp", "non json", content_type="application/json", **autorizzato).json()["error"]["code"] == -32700
    elenco = client.post("/mcp", [{"jsonrpc": "2.0", "id": 1, "method": "ping"}], content_type="application/json", **autorizzato)
    assert elenco.status_code == 400 and elenco.json()["error"]["code"] == -32600
    assert client.post("/mcp", {"id": 1, "method": "ping"}, content_type="application/json", **autorizzato).status_code == 400


def test_origin_solo_se_ben_formata(client, token):
    for origine, stato_http in (("https://claude.ai", 200), ("https://chat.mistral.ai", 200), ("http://localhost:6274", 200),
                                ("null", 403), ("http://malintenzionato.example", 403), ("https://a.example/percorso", 403)):
        assert rpc(client, token, "tools/list", intestazioni={"HTTP_ORIGIN": origine}).status_code == stato_http, origine


def test_il_token_di_un_rinnovo_non_apre(client, collegata):
    assert rpc(client, collegata["refresh_token"], "tools/list").status_code == 401


# ---------- era storica (2025-11-25 e precedenti) ----------

def test_initialize_notifica_ping(client, token):
    r = rpc(client, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "le-chat", "version": "1"}})
    risultato = r.json()["result"]
    assert r.status_code == 200 and risultato["protocolVersion"] == "2025-06-18" and "Mcp-Session-Id" not in r
    assert risultato["capabilities"] == {"tools": {"listChanged": False}} and risultato["serverInfo"]["name"] == "adabox"
    assert len(risultato["instructions"]) <= 512                                           # ChatGPT ne legge i primi 512 caratteri
    futura = rpc(client, token, "initialize", {"protocolVersion": "2031-01-01"}).json()["result"]
    assert futura["protocolVersion"] == "2025-11-25"
    assert rpc(client, token, "notifications/initialized", ident=None).status_code == 202
    assert rpc(client, token, "ping").json()["result"] == {}
    sconosciuto = rpc(client, token, "resources/list")
    assert sconosciuto.status_code == 200 and sconosciuto.json()["error"]["code"] == -32601
    con_versione = rpc(client, token, "tools/list", intestazioni={"HTTP_MCP_PROTOCOL_VERSION": "2025-11-25", "HTTP_MCP_SESSION_ID": "x"})
    assert "resultType" not in con_versione.json()["result"]


def test_tools_list_solo_letture_con_annotazioni(client, token):
    strumenti = {t["name"]: t for t in rpc(client, token, "tools/list").json()["result"]["tools"]}
    assert {"elenco_viste", "descrivi_vista", "cerca_record", "leggi_record", "aggrega_record", "data_e_ora"} <= set(strumenti)
    assert not {"crea_record", "modifica_record", "elimina_record", "cerca_web", "chiedi_esperto", "ricorda", "grafico"} & set(strumenti)
    assert list(strumenti) == sorted(strumenti)                                            # ordine stabile
    for t in strumenti.values():
        assert t["title"] and len(t["name"]) <= 63 and t["inputSchema"]["type"] == "object"
        assert t["annotations"] == {"title": t["title"], "readOnlyHint": True, "destructiveHint": False,
                                    "idempotentHint": True, "openWorldHint": False}
    assert "aziende" not in strumenti["aggrega_record"]["inputSchema"]["properties"]         # mai oltre l'azienda del collegamento
    if "cerca_conoscenza" in strumenti:
        assert "dove" not in strumenti["cerca_conoscenza"]["inputSchema"]["properties"]


@serve_contatti
def test_letture_con_i_permessi_della_persona(client, token, contatti, mario, azienda):
    viste = chiama(client, token, "elenco_viste")
    assert viste["isError"] is False and "contatti.contatti" in viste["content"][0]["text"]
    assert {v["vista"] for v in viste["structuredContent"]["risultati"]} >= {"contatti.contatti"}
    assert "crm.opportunita" not in viste["content"][0]["text"]                            # Mario non ha quel permesso
    trovati = chiama(client, token, "cerca_record", {"vista": "contatti.contatti", "testo": "Rossi"})
    assert "Rossi Srl" in trovati["content"][0]["text"] and "Bianchi" not in trovati["content"][0]["text"]
    assert json.loads(trovati["content"][0]["text"]) == trovati["structuredContent"]
    letto = chiama(client, token, "leggi_record", {"vista": "contatti.contatti", "id": contatti[0].pk})
    assert letto["structuredContent"]["nome"] == "Rossi Srl" and "bottoni_disponibili" not in letto["structuredContent"]
    conto = chiama(client, token, "aggrega_record", {"vista": "contatti.contatti", "per": "citta"})
    assert conto["isError"] is False and "Cagliari" in conto["content"][0]["text"]
    negata = chiama(client, token, "cerca_record", {"vista": "crm.opportunita"})
    assert negata["isError"] is True
    from contatti.models import Contatto
    altra = Azienda.objects.create(nome="Beta Srl")
    estraneo = Contatto.objects.create(azienda=altra, nome="Verdi Snc")
    assert "Verdi" not in chiama(client, token, "cerca_record", {"vista": "contatti.contatti"})["content"][0]["text"]
    assert chiama(client, token, "leggi_record", {"vista": "contatti.contatti", "id": estraneo.pk})["isError"] is True
    fuori = chiama(client, token, "aggrega_record", {"vista": "contatti.contatti", "aziende": "tutte"})
    assert fuori["isError"] is True and "aziende: parametro non previsto" in fuori["content"][0]["text"]


def test_parametri_sbagliati_e_strumenti_fuori_elenco(client, token):
    assert "vista: obbligatorio" in chiama(client, token, "cerca_record", {})["content"][0]["text"]
    sbagliato = chiama(client, token, "leggi_record", {"vista": "contatti.contatti", "id": "uno"})
    assert sbagliato["isError"] is True and "id: atteso integer" in sbagliato["content"][0]["text"]
    for nome in ("crea_record", "cerca_web", "inventato"):
        r = rpc(client, token, "tools/call", {"name": nome, "arguments": {}})
        assert r.json()["error"]["code"] == -32602 and r.json()["error"]["message"].startswith("Unknown tool")
    assert rpc(client, token, "tools/call", {"name": "elenco_viste", "arguments": []}).json()["error"]["code"] == -32602


@serve_contatti
def test_registro_senza_valori(client, token, contatti, mario):
    chiama(client, token, "cerca_record", {"vista": "contatti.contatti", "testo": "Rossi"})
    chiama(client, token, "cerca_record", {"vista": "crm.opportunita", "testo": "segreto"})
    chiama(client, token, "leggi_record", {"vista": "contatti.contatti"})
    righe = list(Chiamata.objects.order_by("pk").values_list("strumento", "vista", "esito", "utente__username"))
    assert righe == [("cerca_record", "contatti.contatti", "fatta", "mario"), ("cerca_record", "crm.opportunita", "errore", "mario"),
                     ("leggi_record", "contatti.contatti", "rifiutata", "mario")]
    testo = json.dumps(list(Chiamata.objects.values()), default=str)
    assert "Rossi" not in testo and "segreto" not in testo
    assert ChatCollegata.objects.get().ultimo_uso is not None


# ---------- era moderna (2026-07-28, senza stato) ----------

def test_discover_e_richieste_senza_handshake(client, token):
    r = rpc(client, token, "server/discover", moderna=True)
    risultato = r.json()["result"]
    assert r.status_code == 200 and risultato["resultType"] == "complete"
    assert risultato["supportedVersions"] == ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26"]
    assert risultato["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "adabox" and risultato["capabilities"] == {"tools": {"listChanged": False}}
    elenco = rpc(client, token, "tools/list", moderna=True).json()["result"]
    assert elenco["resultType"] == "complete" and elenco["cacheScope"] == "private" and elenco["ttlMs"] > 0 and elenco["tools"]
    esito = chiama(client, token, "data_e_ora", {"fuso": "Europe/Rome"}, moderna=True)
    assert esito["resultType"] == "complete" and esito["structuredContent"]["fuso"] == "Europe/Rome"
    assert rpc(client, token, "notifications/cancelled", ident=None, moderna=True).status_code == 202


def test_intestazioni_e_corpo_devono_coincidere(client, token):
    def moderna(metodo, params=None, **intestazioni):
        params = {**(params or {}), "_meta": {META_VERSIONE: "2026-07-28"}}
        base = {"HTTP_MCP_PROTOCOL_VERSION": "2026-07-28", "HTTP_MCP_METHOD": metodo}
        return rpc(client, token, metodo, params, intestazioni={k: v for k, v in {**base, **intestazioni}.items() if v is not None})

    assert moderna("tools/list").status_code == 200
    for cambi in ({"HTTP_MCP_METHOD": None}, {"HTTP_MCP_METHOD": "tools/call"}, {"HTTP_MCP_PROTOCOL_VERSION": None},
                  {"HTTP_MCP_PROTOCOL_VERSION": "2025-11-25"}):
        r = moderna("tools/list", **cambi)
        assert r.status_code == 400 and r.json()["error"]["code"] == -32020, cambi
    chiamata = {"name": "data_e_ora", "arguments": {}}
    assert moderna("tools/call", chiamata).json()["error"]["code"] == -32020                       # manca Mcp-Name
    assert moderna("tools/call", chiamata, HTTP_MCP_NAME="elenco_viste").json()["error"]["code"] == -32020
    assert moderna("tools/call", chiamata, HTTP_MCP_NAME="data_e_ora").json()["result"]["isError"] is False
    codificato = "=?base64?" + base64.b64encode(b"data_e_ora").decode() + "?="
    assert moderna("tools/call", chiamata, HTTP_MCP_NAME=codificato).status_code == 200
    assert moderna("tools/call", chiamata, HTTP_MCP_NAME="=?base64?!!!?=").json()["error"]["code"] == -32020


def test_versione_non_supportata_e_metodo_sconosciuto(client, token):
    futura = rpc(client, token, "tools/list", {"_meta": {META_VERSIONE: "2027-03-01"}},
                 intestazioni={"HTTP_MCP_PROTOCOL_VERSION": "2027-03-01", "HTTP_MCP_METHOD": "tools/list"})
    errore = futura.json()["error"]
    assert futura.status_code == 400 and errore["code"] == -32022 and errore["data"]["requested"] == "2027-03-01"
    assert errore["data"]["supported"][0] == "2026-07-28"
    for metodo in ("ping", "resources/list", "initialize2"):
        r = rpc(client, token, metodo, moderna=True)
        assert r.status_code == 404 and r.json()["error"]["code"] == -32601, metodo
    senza_meta = rpc(client, token, "server/discover")                                             # moderna, ma senza versione
    assert senza_meta.status_code == 400 and senza_meta.json()["error"]["code"] == -32020


# ---------- il collegamento non congela niente ----------

def test_revocato_disattivato_o_spento_smette_subito(client, token, mario, azienda):
    assert rpc(client, token, "tools/list").status_code == 200
    mario.user_permissions.remove(Permission.objects.get(codename="add_chatcollegata"))
    assert rpc(client, token, "tools/list").status_code == 401
    mario.user_permissions.add(Permission.objects.get(codename="add_chatcollegata"))
    parametri.scrivi("connettore_ai.attivo", False, azienda)
    assert rpc(client, token, "tools/list").status_code == 401
    parametri.scrivi("connettore_ai.attivo", True, azienda)
    mario.profilo.aziende.clear()
    assert rpc(client, token, "tools/list").status_code == 401
    mario.profilo.aziende.set([azienda])
    assert rpc(client, token, "tools/list").status_code == 200
    mario.is_active = False
    mario.save()
    assert rpc(client, token, "tools/list").status_code == 401


@serve_contatti
def test_permesso_tolto_dopo_il_collegamento(client, token, contatti, mario):
    assert chiama(client, token, "cerca_record", {"vista": "contatti.contatti"})["isError"] is False
    mario.user_permissions.remove(Permission.objects.get(codename="view_contatto"))
    assert chiama(client, token, "cerca_record", {"vista": "contatti.contatti"})["isError"] is True


def test_strumento_spento_dall_amministratore(client, token, azienda):
    from ai.models import StrumentoSpento
    StrumentoSpento.objects.create(nome="aggrega_record", azienda=azienda)
    nomi = {t["name"] for t in rpc(client, token, "tools/list").json()["result"]["tools"]}
    assert "aggrega_record" not in nomi and "cerca_record" in nomi
    assert rpc(client, token, "tools/call", {"name": "aggrega_record", "arguments": {"vista": "contatti.contatti"}}).json()["error"]["code"] == -32602


@serve_contatti
def test_solo_le_app_del_consenso(client, mario, documenti, contatti):
    mario.user_permissions.add(*Permission.objects.filter(codename__in=["view_opportunita", "view_documento"]))
    codice = consenti(client, mario, DOCUMENTO_CLAUDE, CLAUDE, quali="alcune", app=["contatti"])
    token = scambia(client, DOCUMENTO_CLAUDE, CLAUDE, codice).json()["access_token"]
    viste = chiama(client, token, "elenco_viste")["structuredContent"]["risultati"]
    assert viste and {v["app"] for v in viste} == {"contatti"}
    assert chiama(client, token, "cerca_record", {"vista": "contatti.contatti"})["isError"] is False
    for argomenti in ({"vista": "crm.opportunita"}, {"vista": "contatti.contatti", "inventato": 1}):
        assert chiama(client, token, "cerca_record", argomenti)["isError"] is True
    assert "non è tra quelle comprese" in chiama(client, token, "elenco_viste", {"app": "crm"})["content"][0]["text"]
    nomi = {t["name"] for t in rpc(client, token, "tools/list").json()["result"]["tools"]}
    assert "leggi_documento" not in nomi                                                   # è dell'app Documenti, non compresa
    assert Chiamata.objects.filter(esito=Chiamata.RIFIUTATA, motivo="app fuori dal collegamento").count() == 2


def test_troppe_chiamate(client, token, monkeypatch):
    monkeypatch.setattr(mcp, "CHIAMATE_AL_MINUTO", 2)
    esiti = [rpc(client, token, "tools/list").status_code for _ in range(3)]
    assert esiti == [200, 200, 429]


# ---------- dati personali ----------

@pytest.fixture
def servizio_pii(monkeypatch):
    """Un servizio di protezione finto: riconosce «Rossi Srl» e «Bianchi Spa» come nomi."""
    from ai import protezione as di_ada
    stato_servizio = {"giu": False, "url": "http://pii.interno"}

    def spans(url, testo, esclusi):
        if stato_servizio["giu"]:
            raise di_ada.ServizioNonDisponibile("spento")
        trovati = []
        for nome in ("Rossi Srl", "Bianchi Spa"):
            inizio = testo.find(nome)
            while inizio >= 0:
                trovati.append((inizio, inizio + len(nome), "FULLNAME"))
                inizio = testo.find(nome, inizio + 1)
        return trovati
    monkeypatch.setattr(di_ada, "spans", spans)
    monkeypatch.setattr(di_ada, "impostazioni", lambda: (stato_servizio["url"], ()))
    monkeypatch.setattr(di_ada, "plausibile", lambda *a: True)
    return stato_servizio


@serve_contatti
def test_dati_personali_mascherati_e_segnaposto_che_tornano(client, token, contatti, azienda, servizio_pii):
    parametri.scrivi("connettore_ai.maschera", True, azienda)
    elenco = chiama(client, token, "cerca_record", {"vista": "contatti.contatti"})
    testo = elenco["content"][0]["text"]
    assert "Rossi" not in testo and "Bianchi" not in testo and "[FULLNAME_1]" in testo and "[FULLNAME_2]" in testo
    assert "Rossi" not in json.dumps(elenco["structuredContent"]) and Chiamata.objects.get().mascherati >= 2
    mappa = ChatCollegata.objects.get().segnaposto
    assert sorted(mappa.values()) == ["Bianchi Spa", "Rossi Srl"]
    segnaposto = next(s for s, v in mappa.items() if v == "Rossi Srl")
    # la chat cerca con il segnaposto: adabox cerca il nome vero e risponde di nuovo con il segnaposto
    mirato = chiama(client, token, "cerca_record", {"vista": "contatti.contatti", "testo": segnaposto})["content"][0]["text"]
    assert segnaposto in mirato and "Rossi" not in mirato and len(ChatCollegata.objects.get().segnaposto) == 2
    altro = next(s for s in mappa if s != segnaposto)
    assert altro not in mirato


@serve_contatti
def test_senza_servizio_di_protezione_non_esce_niente(client, token, contatti, azienda, servizio_pii):
    parametri.scrivi("connettore_ai.maschera", True, azienda)
    for guasto in ({"giu": True}, {"giu": False, "url": ""}):
        servizio_pii.update(guasto)
        esito = chiama(client, token, "cerca_record", {"vista": "contatti.contatti"})
        assert esito["isError"] is True and "Rossi" not in json.dumps(esito) and "non è uscito nessun dato" in esito["content"][0]["text"]
    assert Chiamata.objects.filter(esito=Chiamata.ERRORE).count() == 2
    parametri.scrivi("connettore_ai.maschera", False, azienda)
    assert "Rossi Srl" in chiama(client, token, "cerca_record", {"vista": "contatti.contatti"})["content"][0]["text"]
    assert protezione.maschera(ChatCollegata.objects.get(), "Rossi Srl") == ("Rossi Srl", 0)
