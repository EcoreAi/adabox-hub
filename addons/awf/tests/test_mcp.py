import datetime
import re

import pytest
from django.utils import timezone

from awf.models import Chiamata, Collegamento
from core.models import Azienda, Messaggio
from todo.models import Attivita

from .conftest import BEARER, ingaggio

NOME_AGATE = re.compile(r"^[a-z][a-z0-9_]*$")


def rpc(client, metodo, params=None, bearer=BEARER, ident=1):
    corpo = {"jsonrpc": "2.0", "method": metodo, "params": params or {}}
    if ident is not None:
        corpo["id"] = ident
    intestazioni = {"HTTP_AUTHORIZATION": f"Bearer {bearer}"} if bearer else {}
    return client.post("/awf/mcp/", corpo, content_type="application/json", **intestazioni)


def chiama(client, nome, argomenti, meta=None):
    params = {"name": nome, "arguments": argomenti}
    if meta:
        params["_meta"] = meta
    r = rpc(client, "tools/call", params)
    assert r.status_code == 200
    return r.json()["result"]


@pytest.fixture
def attivita(db):
    return Attivita.objects.create(titolo="Ordinare la carta", azienda=Azienda.objects.get(pk=1))


def test_initialize_e_notifica(client, collegato, ammesse):
    r = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    risultato = r.json()["result"]
    assert r.status_code == 200 and risultato["protocolVersion"] == "2025-06-18"
    assert risultato["capabilities"] == {"tools": {"listChanged": False}}
    assert rpc(client, "notifications/initialized", ident=None).status_code == 202
    assert rpc(client, "ping").json()["result"] == {}


def test_bearer_sbagliato_o_assente_401(client, collegato, ammesse):
    assert rpc(client, "tools/list", bearer="awf_sbagliato").status_code == 401
    r = rpc(client, "tools/list", bearer=None)
    assert r.status_code == 401 and r["WWW-Authenticate"].startswith("Bearer")
    assert client.get("/awf/mcp/", HTTP_AUTHORIZATION=f"Bearer {BEARER}").status_code == 405


def test_senza_collegamento_nessun_bearer_vale(client, db):
    assert rpc(client, "tools/list", bearer="").status_code == 401
    assert rpc(client, "tools/list", bearer="qualcosa").status_code == 401


def test_tools_list_solo_ammessi_con_annotazioni_e_viste(client, collegato, ammesse):
    strumenti = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert set(strumenti) == {"elenco_viste", "cerca_record", "leggi_record", "modifica_record", "crea_record"}
    assert all(NOME_AGATE.match(n) for n in strumenti)
    assert strumenti["cerca_record"]["annotations"]["readOnlyHint"] is True
    assert "enum" not in strumenti["cerca_record"]["inputSchema"]["properties"]["vista"]
    modifica = strumenti["modifica_record"]
    assert modifica["annotations"] == {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                                       "openWorldHint": False}
    assert modifica["inputSchema"]["properties"]["vista"]["enum"] == ["todo.attivita"]
    assert "proposta" not in modifica["description"] and "Scrive nel gestionale" in modifica["description"]


def test_irreversibile_dichiarato_distruttivo(client, collegato, ammesse):
    from awf.models import OperazioneAmmessa
    OperazioneAmmessa.objects.create(strumento="elimina_record", vista="todo.attivita")
    strumenti = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert strumenti["elimina_record"]["annotations"]["destructiveHint"] is True


def test_strumento_sconosciuto_o_non_ammesso(client, collegato, ammesse):
    r = rpc(client, "tools/call", {"name": "inventato", "arguments": {}}).json()
    assert r["error"]["code"] == -32602
    r = rpc(client, "tools/call", {"name": "elimina_record", "arguments": {"vista": "todo.attivita", "id": 1}}).json()
    assert r["error"]["code"] == -32602                  # esiste nell'assistente ma non è ammesso


def test_lettura_con_l_agente_e_l_azienda_degli_agenti(client, collegato, ammesse, attivita):
    altra = Azienda.objects.create(nome="Altra Srl")
    Attivita.objects.create(titolo="Di un'altra azienda", azienda=altra)
    r = chiama(client, "leggi_record", {"vista": "todo.attivita", "id": attivita.pk}, {"agentlia/agent": "Buyer"})
    assert r["isError"] is False and "Ordinare la carta" in r["content"][0]["text"]
    assert isinstance(r["structuredContent"], dict)
    r = chiama(client, "cerca_record", {"vista": "todo.attivita"})
    assert "Ordinare la carta" in r["content"][0]["text"] and "Di un'altra azienda" not in r["content"][0]["text"]
    assert Chiamata.objects.filter(strumento="leggi_record", agente__nome="Buyer", esito="eseguita").exists()


def test_lettura_su_vista_non_concessa_non_vede_nulla(client, collegato, ammesse):
    r = chiama(client, "cerca_record", {"vista": "core.aziende"})        # strumento ammesso, permesso no
    assert r["isError"] is True and "core.aziende" not in r["content"][0]["text"]


def test_scrittura_ammessa_eseguita_con_nota_nel_chatter(client, collegato, ammesse, attivita):
    r = chiama(client, "modifica_record", {"vista": "todo.attivita", "id": attivita.pk, "campi": {"stato": "in_corso"}},
               {"agentlia/agent": "Buyer", "idempotencyKey": "k-1"})
    assert r["isError"] is False, r
    attivita.refresh_from_db()
    assert attivita.stato == "in_corso"
    assert r["structuredContent"]["record"] == {"modello": "todo.attivita", "id": attivita.pk}
    nota = Messaggio.objects.filter(object_id=attivita.pk, corpo__startswith="Tramite agente AWF Buyer").get()
    assert nota.autore.username == "awf-buyer" and nota.tipo == "sistema"
    c = Chiamata.objects.get(strumento="modifica_record")
    assert c.esito == "eseguita" and c.agente.nome == "Buyer" and c.anteprima["titolo"]
    # la stessa chiave di idempotenza (Agate che ritenta) non esegue di nuovo
    Attivita.objects.filter(pk=attivita.pk).update(stato="aperta")
    r2 = chiama(client, "modifica_record", {"vista": "todo.attivita", "id": attivita.pk, "campi": {"stato": "in_corso"}},
                {"agentlia/agent": "Buyer", "idempotencyKey": "k-1"})
    attivita.refresh_from_db()
    assert r2["structuredContent"] == r["structuredContent"] and attivita.stato == "aperta"


def test_agente_come_argomento_e_agente_tecnico(client, collegato, ammesse, attivita):
    r = chiama(client, "modifica_record", {"vista": "todo.attivita", "id": attivita.pk,
                                           "campi": {"stato": "in_corso"}, "agente": "Magazziniere"})
    assert r["isError"] is False
    assert Messaggio.objects.filter(object_id=attivita.pk, corpo__startswith="Tramite agente AWF Magazziniere").exists()
    r = chiama(client, "modifica_record", {"vista": "todo.attivita", "id": attivita.pk, "campi": {"stato": "fatta"}})
    assert r["isError"] is False
    assert Messaggio.objects.filter(object_id=attivita.pk, autore__username="awf-tecnico").exists()
    r = chiama(client, "leggi_record", {"vista": "todo.attivita", "id": attivita.pk}, {"agent": "Sconosciuto"})
    assert r["isError"] is True and r["structuredContent"]["stato"] == "agente_sconosciuto"


def test_scrittura_su_vista_non_ammessa_rifiutata_senza_valori(client, collegato, ammesse):
    azienda = Azienda.objects.get(pk=1)
    r = chiama(client, "modifica_record", {"vista": "core.aziende", "id": azienda.pk,
                                           "campi": {"nome": "Nome Segreto Spa"}})
    azienda.refresh_from_db()
    assert r["isError"] is True and azienda.nome != "Nome Segreto Spa"
    testo = r["content"][0]["text"]
    assert "vista: non ammessa" in testo and "Nome Segreto" not in testo and "core.aziende" not in testo
    assert Chiamata.objects.get(strumento="modifica_record").esito == "rifiutata"


def test_parametri_non_previsti_o_mancanti(client, collegato, ammesse, attivita):
    r = chiama(client, "leggi_record", {"vista": "todo.attivita", "inventato": "valore-privato"})
    testo = r["content"][0]["text"]
    assert r["isError"] and "inventato: parametro non previsto" in testo and "id: obbligatorio" in testo
    assert "valore-privato" not in testo


def test_errore_dello_strumento_senza_valori(client, collegato, ammesse, attivita):
    r = chiama(client, "modifica_record", {"vista": "todo.attivita", "id": attivita.pk,
                                           "campi": {"campo_privato_xyz": "Mario Rossi"}})
    assert r["isError"] is True and "Mario Rossi" not in r["content"][0]["text"]


@pytest.mark.parametrize("stato", [
    {"observe_until": (timezone.now() + datetime.timedelta(days=2)).isoformat()},
    {"status": "paused"},
    {"blocked": {"code": "engagement_paused", "detail": "pausa"}},
])
def test_osservazione_ferma_le_scritture_non_le_letture(client, collegato, ammesse, attivita, stato):
    Collegamento.objects.filter(pk=1).update(ultimo_stato=ingaggio(**stato))
    r = chiama(client, "modifica_record", {"vista": "todo.attivita", "id": attivita.pk, "campi": {"stato": "fatta"}},
               {"agentlia/agent": "Buyer"})
    attivita.refresh_from_db()
    assert r["isError"] is True and attivita.stato == "aperta"
    assert r["structuredContent"]["codice"] == 409 and r["structuredContent"]["stato"] == "osservazione"
    c = Chiamata.objects.get(strumento="modifica_record")
    assert c.esito == "osservazione" and c.anteprima["titolo"].startswith("Modifica")      # cosa sarebbe successo
    assert c.argomenti["campi"] == {"stato": "fatta"}
    assert not Messaggio.objects.filter(corpo__startswith="Tramite agente AWF").exists()
    r = chiama(client, "leggi_record", {"vista": "todo.attivita", "id": attivita.pk})
    assert r["isError"] is False


def test_osservazione_dalle_impostazioni(client, collegato, ammesse, attivita):
    from core import parametri
    parametri.scrivi("awf.osservazione", True)
    r = chiama(client, "modifica_record", {"vista": "todo.attivita", "id": attivita.pk, "campi": {"stato": "fatta"}})
    assert r["structuredContent"]["codice"] == 409


def test_senza_azienda_niente_operazioni(client, collegato, ammesse, attivita):
    Collegamento.objects.filter(pk=1).update(azienda=None)
    r = chiama(client, "leggi_record", {"vista": "todo.attivita", "id": attivita.pk})
    assert r["isError"] is True and r["structuredContent"]["stato"] == "non_configurato"
