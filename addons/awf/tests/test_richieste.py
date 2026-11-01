import hashlib

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied

from awf import fabbrica, lavori, operazioni
from awf.models import Agente, Collegamento, OperazioneAmmessa, RichiestaAgenti
from core.models import Azienda

from .conftest import AGENTI, ingaggio
from .test_mcp import rpc

FORGE = "https://fabbrica.esempio.it"
SQUADRA = {
    "slug": "lead-crm-adabox", "version": 1, "name": "Lead e CRM", "department": "crm",
    "description": "Qualifica i lead e tiene in ordine le opportunità.", "kind": "django", "saas": "adabox",
    "observe_days": 3,
    "members": [{"role": "adabox.crm.qualifier", "name": "Qualificatore lead", "position": "single",
                 "kind": "conversational", "description": "Dà un punteggio ai lead"}],
    "operations": [{"tool": "awf.cerca_record", "view": "crm.opportunita", "effect": "read", "risk": "low",
                    "line": ""},
                   {"tool": "awf.modifica_record", "view": "crm.opportunita", "effect": "write", "risk": "medium",
                    "line": "Cambia priorità e probabilità"},
                   {"tool": "awf.lancia_razzi", "view": "", "effect": "irreversible", "risk": "high"}],
    "price": {"pricing": "mixed", "period_eur": "150", "period_days": 7, "task_eur": "0", "llm_markup": "1.4",
              "prepaid_credit_eur": "30"},
    "caps": {"llm_eur_max": 60}}
ID = "6f1c2a9e-0b7d-4c1e-9a55-1d2e3f405162"
STATO = f"/api/hire-requests/{ID}"


@pytest.fixture(autouse=True)
def cache_pulita():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def fabbrica_nota(db):
    c = Collegamento.attuale()
    c.forge_url, c.base_url, c.azienda = FORGE, "https://erp.esempio.it", Azienda.objects.get(pk=1)
    c.save()
    return c


@pytest.fixture
def listino(finta, fabbrica_nota):
    finta.risposte["/api/catalog"] = (200, {"teams": [SQUADRA, {"slug": "Non Valido!"}]})
    finta.risposte["/api/hire-requests"] = (201, {"request_id": ID, "token": "wfr_" + "r" * 40,
                                                  "status": "received"})
    return finta


def _stato(status, **altro):
    return (200, {"request_id": ID, "status": status, "message": "", "team": {"slug": SQUADRA["slug"]},
                  "weeks": 4, "approve_url": None, "engagement": None, "plugin_token": None, "install_id": None,
                  **altro})


def _richiesta(capo=None, **altro):
    return fabbrica.richiedi(SQUADRA["slug"], 1, 4, "circa 10 opportunità al giorno", capo,
                             Azienda.objects.get(pk=1), **altro)


# ---------- catalogo ----------

def test_catalogo_letto_controllato_e_tenuto(listino):
    squadre = fabbrica.catalogo()
    assert [s["slug"] for s in squadre] == ["lead-crm-adabox"]                    # quella non valida resta fuori
    assert squadre[0]["operazioni"][1] == {"tool": "awf.modifica_record", "view": "crm.opportunita",
                                           "effect": "write", "risk": "medium", "line": "Cambia priorità e probabilità"}
    fabbrica.catalogo()
    fabbrica.catalogo("CRM")
    url = [r["url"] for r in listino.richieste]
    assert url == [f"{FORGE}/api/catalog?kind=django&saas=adabox",
                   f"{FORGE}/api/catalog?kind=django&saas=adabox&department=crm"]
    assert "Authorization" not in listino.richieste[0]["intestazioni"]                # pubblico


def test_pagina_del_catalogo(client, superuser, listino):
    pagina = client.get("/awf/catalogo/").content.decode()
    assert "Lead e CRM" in pagina and "Qualificatore lead" in pagina and "Dà un punteggio ai lead" in pagina
    assert "Leggere: Opportunità" in pagina and "Modificare: Opportunità — Cambia priorità e probabilità" in pagina
    assert "awf.lancia_razzi" not in pagina and "Operazioni irreversibili: le viste concesse (irreversibile)" in pagina
    assert "150 € ogni 7 giorni + consumo AI (ricarico 40%) · credito iniziale 30 €" in pagina
    assert "3 giorni di prova" in pagina and "lo approva nella console di Agate" in pagina


def test_catalogo_con_la_fabbrica_giu(client, superuser, finta, fabbrica_nota):
    finta.risposte["/api/catalog"] = (fabbrica.ErroreFabbrica("fabbrica non raggiungibile (URLError)"), {})
    r = client.get("/awf/catalogo/")
    assert r.status_code == 200 and "La fabbrica non risponde" in r.content.decode()
    finta.risposte["/api/catalog"] = (503, {})
    assert "La fabbrica non risponde" in client.get("/awf/catalogo/").content.decode()


def test_catalogo_senza_indirizzo_lo_chiede(client, superuser, finta, monkeypatch):
    monkeypatch.delenv("AWF_FORGE_URL", raising=False)
    pagina = client.get("/awf/catalogo/").content.decode()
    assert 'name="forge_url"' in pagina and finta.richieste == []
    client.post("/awf/catalogo/", {"azione": "fabbrica", "forge_url": "ftp://x"})
    assert Collegamento.attuale().forge_url == ""
    client.post("/awf/catalogo/", {"azione": "fabbrica", "forge_url": FORGE + "/"})
    assert Collegamento.attuale().forge_url == FORGE


def test_pagine_nuove_solo_per_chi_gestisce_awf(client, utente):
    client.force_login(utente)
    assert client.get("/awf/catalogo/").status_code == 403
    assert client.get("/awf/richieste/").status_code == 403


# ---------- richiesta ----------

def test_richiesta_dalla_pagina_segue_il_contratto(client, superuser, listino, ammesse):
    from agate.models import Collegamento as CollegamentoAgate
    CollegamentoAgate.objects.create(gateway_url="https://api.agate.esempio.it",
                                     console_url="https://console.agate.esempio.it")
    superuser.first_name, superuser.last_name = "Mario", "Rossi"
    superuser.save()
    azienda = Azienda.objects.get(pk=1)
    azienda.partita_iva = "01234567890"
    azienda.save()
    r = client.post("/awf/catalogo/", {"azione": "richiedi", "team": SQUADRA["slug"], "versione": 1,
                                       "settimane": 4, "note": "circa 10 opportunità al giorno"})
    assert r.status_code == 302 and r["Location"] == "/awf/richieste/"
    invio = next(x for x in listino.richieste if x["metodo"] == "POST")
    assert invio["url"] == f"{FORGE}/api/hire-requests"
    corpo = invio["corpo"]
    assert {k: corpo[k] for k in ("team", "team_version", "weeks", "notes")} == {
        "team": "lead-crm-adabox", "team_version": 1, "weeks": 4, "notes": "circa 10 opportunità al giorno"}
    assert corpo["company"] == {"name": azienda.nome, "vat": "01234567890", "email": "root@example.com",
                                "contact": "Mario Rossi"}
    plugin = corpo["plugin"]
    assert plugin["kind"] == "django" and plugin["saas"] == "adabox" and plugin["base_url"] == "https://erp.esempio.it"
    assert plugin["version"] == operazioni.versione()
    assert plugin["operations"] == [e.dichiarazione() for e in operazioni.esposte()]
    assert {o["name"] for o in plugin["operations"]} >= {"cerca_record", "modifica_record"}
    assert corpo["agate"] == {"gateway_url": "https://api.agate.esempio.it",
                              "console_url": "https://console.agate.esempio.it"}

    rich = RichiestaAgenti.objects.get()
    assert rich.request_id == ID and rich.stato == "inviata" and rich.token() == "wfr_" + "r" * 40
    assert "wfr_" not in rich.token_cifrato and rich.creata_da == superuser and rich.team_nome == "Lead e CRM"
    assert rich.operazioni == fabbrica.catalogo()[0]["operazioni"]
    assert not Collegamento.attuale().collegato                                       # niente collegamento ancora


@pytest.mark.parametrize("stato,messaggio", [(409, "è cambiata"), (429, "10 l&#x27;ora"), (404, "non più in catalogo")])
def test_richiesta_rifiutata_dalla_fabbrica(client, superuser, listino, stato, messaggio):
    listino.risposte["/api/hire-requests"] = (stato, {"detail": "no"})
    r = client.post("/awf/catalogo/", {"azione": "richiedi", "team": SQUADRA["slug"], "versione": 1,
                                       "settimane": 4}, follow=True)
    assert messaggio in r.content.decode() and not RichiestaAgenti.objects.exists()


def test_richiesta_controllata_prima_di_partire(listino):
    for team, settimane in [("inesistente", 4), (SQUADRA["slug"], 0), (SQUADRA["slug"], 53)]:
        with pytest.raises(fabbrica.ErroreFabbrica):
            fabbrica.richiedi(team, 1, settimane)
    with pytest.raises(fabbrica.ErroreFabbrica, match="1000"):
        fabbrica.richiedi(SQUADRA["slug"], 1, 4, "x" * 1001)
    assert not [x for x in listino.richieste if x["metodo"] == "POST"]


# ---------- stato, collegamento automatico, ritiro ----------

def test_dalla_richiesta_al_collegamento_da_solo(listino, superuser):
    c = Collegamento.attuale()
    c.mcp_impronta, c.mcp_indizio = "a" * 64, "awf_vecc"                             # di un'installazione vecchia
    c.save()
    r = _richiesta(superuser)
    listino.risposte[STATO] = [
        _stato("received"),
        _stato("proposed", approve_url="https://console.agate.esempio.it/console/engagements/eng_1/",
               message="Contratto pronto: approvatelo in Agate"),
        _stato("connected", plugin_token="wpt_" + "p" * 40, install_id="ins_9", engagement=ingaggio()),
        _stato("connected")]
    assert "richieste aperte: 1" in lavori.richieste()
    r.refresh_from_db()
    assert r.stato == "inviata" and r.letta_il is not None
    lettura = listino.richieste[-1]
    assert lettura["metodo"] == "GET" and lettura["url"] == FORGE + STATO
    assert lettura["intestazioni"]["Authorization"] == "Bearer wfr_" + "r" * 40

    lavori.richieste()
    r.refresh_from_db()
    assert r.stato == "da_approvare" and r.approve_url.endswith("/eng_1/") and "approvatelo" in r.messaggio

    lavori.richieste()
    r.refresh_from_db()
    assert r.stato == "collegata" and r.collegata_il is not None
    c = Collegamento.attuale()
    assert c.collegato and c.token() == "wpt_" + "p" * 40 and "wpt_" not in c.token_cifrato
    assert c.install_id == "ins_9" and c.forge_url == FORGE and c.base_url == "https://erp.esempio.it"
    assert c.azienda_id == 1 and c.ingaggio["status"] == "active"
    assert c.mcp_impronta == "a" * 64                         # il bearer già dato ad Agate resta: è di adabox, non dell'ingaggio
    assert {a.nome for a in Agente.objects.filter(attivo=True, tecnico=False)} == {a["name"] for a in AGENTI}

    letture = len(listino.richieste)
    assert lavori.richieste() == "nessuna richiesta aperta"                          # chiusa: non si legge più
    assert len(listino.richieste) == letture


def test_collegata_senza_token_non_torna_indietro(listino):
    r = _richiesta()
    listino.risposte[STATO] = _stato("connected")
    fabbrica.aggiorna(r)
    assert r.stato == "collegata" and r.collegata_il is None and "wfc_" in r.messaggio
    assert not Collegamento.attuale().collegato


def test_rifiutata_con_il_motivo(client, superuser, listino):
    r = _richiesta(superuser)
    listino.risposte[STATO] = _stato("rejected", message="Volumi troppo alti per questa squadra")
    pagina = client.get("/awf/richieste/").content.decode()                           # all'apertura si legge lo stato
    r.refresh_from_db()
    assert r.stato == "rifiutata" and "Volumi troppo alti" in pagina and "Rifiutata" in pagina


def test_ritira(client, superuser, listino):
    r = _richiesta(superuser)
    listino.risposte[STATO] = _stato("received")
    listino.risposte[f"DELETE {STATO}"] = (204, {})
    pagina = client.get("/awf/richieste/").content.decode()
    assert 'value="ritira"' in pagina
    client.post("/awf/richieste/", {"pk": r.pk, "azione": "ritira"})
    r.refresh_from_db()
    assert r.stato == "ritirata" and listino.richieste[-1]["metodo"] == "DELETE"
    assert listino.richieste[-1]["intestazioni"]["Authorization"] == "Bearer wfr_" + "r" * 40
    r.stato = "da_approvare"
    r.save()
    with pytest.raises(fabbrica.ErroreFabbrica, match="console di Agate"):
        fabbrica.ritira(r)


# ---------- dopo il collegamento: operazioni con un clic e bearer per Agate ----------

@pytest.fixture
def collegata(listino, superuser):
    r = _richiesta(superuser)
    listino.risposte[STATO] = _stato("connected", plugin_token="wpt_" + "p" * 40, install_id="ins_9",
                                     engagement=ingaggio())
    listino.risposte["/api/plugins/heartbeat"] = (200, {"engagement": ingaggio()})
    fabbrica.aggiorna(r)
    OperazioneAmmessa.objects.create(strumento="cerca_record", vista="crm.opportunita")
    return r


def test_operazioni_della_squadra_con_un_clic(client, collegata):
    pagina = client.get("/awf/richieste/").content.decode()
    assert "già ammessa" in pagina and "da ammettere" in pagina and "non disponibile qui" in pagina
    assert "Ammetti con un clic" in pagina and "Genera indirizzo e bearer" in pagina
    buyer = User.objects.get(username="awf-buyer")
    assert not buyer.has_perm("crm.change_opportunita")
    r = client.post("/awf/richieste/", {"pk": collegata.pk, "azione": "ammetti"}, follow=True)
    assert "1 aggiunta" in r.content.decode() and "1 non disponibile" in r.content.decode()
    voci = set(OperazioneAmmessa.objects.values_list("strumento", "vista"))
    assert {("cerca_record", "crm.opportunita"), ("modifica_record", "crm.opportunita")} <= voci
    assert not OperazioneAmmessa.objects.filter(strumento__in=["lancia_razzi", "awf.modifica_record"]).exists()
    buyer = User.objects.get(username="awf-buyer")
    assert buyer.has_perm("crm.change_opportunita") and buyer.has_perm("crm.view_opportunita")
    assert "/api/plugins/heartbeat" in collegata_ultima_url(client)
    client.post("/awf/richieste/", {"pk": collegata.pk, "azione": "ammetti"})       # di nuovo: niente doppioni
    assert OperazioneAmmessa.objects.filter(strumento="modifica_record").count() == 1


def collegata_ultima_url(client):
    return fabbrica.trasporto.richieste[-1]["url"]


def test_bearer_per_agate_si_vede_una_volta(client, collegata):
    pagina = client.post("/awf/richieste/", {"pk": collegata.pk, "azione": "bearer"}).content.decode()
    bearer = next(p for p in pagina.split("<code>") if p.startswith("awf_")).split("</code>")[0]
    assert "https://erp.esempio.it/awf/mcp/" in pagina and "Applicazione dell'azienda (server MCP)" in pagina
    assert "<code>awf</code>" in pagina
    c = Collegamento.attuale()
    assert c.mcp_impronta == hashlib.sha256(bearer.encode()).hexdigest()
    seguente = client.get("/awf/richieste/").content.decode()
    assert bearer not in seguente and "Genera un nuovo bearer" in seguente
    assert rpc(client, "tools/list", bearer=bearer).status_code == 200


def test_adabox_si_prepara_prima_della_proposta_e_il_bearer_resta(client, superuser, listino):
    """Agate accetta il contratto solo con gli strumenti della squadra già attivi: operazioni e bearer si fanno appena
    la richiesta parte, e il collegamento da solo non toglie il bearer già dato ad Agate."""
    r = _richiesta(superuser)
    listino.risposte[STATO] = _stato("received")
    pagina = client.get("/awf/richieste/").content.decode()
    assert "Prepara adabox per la squadra" in pagina and "Ammetti con un clic" in pagina
    client.post("/awf/richieste/", {"pk": r.pk, "azione": "ammetti"})
    assert OperazioneAmmessa.objects.filter(strumento="modifica_record", vista="crm.opportunita").exists()
    pagina = client.post("/awf/richieste/", {"pk": r.pk, "azione": "bearer"}).content.decode()
    bearer = next(p for p in pagina.split("<code>") if p.startswith("awf_")).split("</code>")[0]
    impronta = Collegamento.attuale().mcp_impronta
    assert impronta == hashlib.sha256(bearer.encode()).hexdigest()

    listino.risposte[STATO] = _stato("connected", plugin_token="wpt_" + "p" * 40, install_id="ins_9",
                                     engagement=ingaggio())
    lavori.richieste()
    c = Collegamento.attuale()
    assert c.collegato and c.mcp_impronta == impronta                    # Agate continua a raggiungere adabox
    assert rpc(client, "tools/list", bearer=bearer).status_code == 200


def test_bearer_e_operazioni_non_per_richieste_chiuse(client, superuser, listino):
    r = _richiesta(superuser)
    RichiestaAgenti.objects.filter(pk=r.pk).update(stato="ritirata")
    client.post("/awf/richieste/", {"pk": r.pk, "azione": "bearer"})
    client.post("/awf/richieste/", {"pk": r.pk, "azione": "ammetti"})
    assert Collegamento.attuale().mcp_impronta == ""
    assert not OperazioneAmmessa.objects.filter(strumento="modifica_record").exists()


# ---------- assistente AI ----------

@pytest.fixture
def scena(db, client, listino):
    from ai.models import AnelloCatena, Conversazione, Modello, Profilo, Provider
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto")
    AnelloCatena.objects.create(profilo=Profilo.objects.create(nome="Chat", compito="chat"), modello=modello)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    return {"capo": capo, "azienda": Azienda.objects.get(pk=1), "client": client, "finta": listino,
            "conversazione": Conversazione.objects.create(utente=capo, titolo="Agenti")}


def _turno(scena, chiamate, testo="Ho bisogno di agenti AI di AWF per il mio reparto CRM, mi puoi aiutare?"):
    from ai import motore
    from ai.gateway import finto
    with finto.con_copione([[("strumento", nome, argomenti) for nome, argomenti in chiamate], ["Ecco."]]):
        motore.avvia(scena["conversazione"], testo, scena["capo"], scena["azienda"])
    from ai.models import Evento
    return Evento.objects.filter(tipo="strumento").last().dati["risultati"]


def test_assistente_legge_il_catalogo(scena):
    risultato = _turno(scena, [("catalogo_agenti", {"reparto": "crm"})])[0]
    assert not risultato["errore"]
    testo = risultato["contenuto"]
    assert "lead-crm-adabox" in testo and "Qualificatore lead" in testo and "Modificare: Opportunità" in testo
    assert "ricarico 40%" in testo and '"giorni_di_prova": 3' in testo


def test_assistente_propone_e_alla_conferma_chiede_la_squadra(scena):
    from ai.models import Proposta
    finta = scena["finta"]
    risultato = _turno(scena, [("richiedi_squadra", {"team": "lead-crm-adabox", "settimane": 4,
                                                     "note": "CRM, circa 10 opportunità al giorno"})])[0]
    assert not risultato["errore"] and "NON è ancora eseguita" in risultato["contenuto"]
    p = Proposta.objects.get()
    assert p.strumento == "richiedi_squadra" and p.rischio == "scrittura" and "Lead e CRM" in p.titolo
    dettagli = {d["campo"]: d["dopo"] for d in p.dettagli}
    assert dettagli["Costo fisso stimato"] == "600 €" and "ricarico del 40%" in dettagli["Consumo AI"]
    assert "console di Agate" in dettagli["Poi"] and dettagli["Durata"] == "4 settimane"
    assert not [x for x in finta.richieste if x["metodo"] == "POST"] and not RichiestaAgenti.objects.exists()

    r = scena["client"].post(f"/ai/proposta/{p.pk}/conferma/", {}, HTTP_HX_REQUEST="true")
    p.refresh_from_db()
    assert r.status_code == 200 and p.stato == "eseguita" and p.url == "/awf/richieste/"
    assert "Prossimi passi" in p.esito and "Agenti → Richieste" in p.esito
    invio = next(x for x in finta.richieste if x["metodo"] == "POST")
    assert invio["corpo"]["weeks"] == 4 and invio["corpo"]["notes"] == "CRM, circa 10 opportunità al giorno"
    rich = RichiestaAgenti.objects.get()
    assert rich.creata_da == scena["capo"] and rich.azienda_id == 1

    finta.risposte[STATO] = _stato("proposed", approve_url="https://console.agate.esempio.it/console/engagements/e/")
    stato = _turno(scena, [("stato_richieste_agenti", {})], testo="A che punto siamo?")[0]
    assert not stato["errore"] and "Da approvare in Agate" in stato["contenuto"]
    assert "console.agate.esempio.it/console/engagements/e/" in stato["contenuto"]
    assert "Lead e CRM" in stato["contenuto"]


def test_strumenti_per_gli_agenti_solo_a_chi_gestisce_awf(listino, utente):
    from ai import strumenti
    from ai.models import Conversazione
    nomi = {s.nome for s in strumenti.disponibili(utente)}
    assert not nomi & {"catalogo_agenti", "richiedi_squadra", "stato_richieste_agenti"}
    registro = {s.nome: s for s in strumenti.disponibili(User.objects.create_superuser("capo", "c@e.it", "x"))}
    contesto = strumenti.Contesto(utente=utente, azienda=Azienda.objects.get(pk=1),
                                  conversazione=Conversazione.objects.create(utente=utente))
    with pytest.raises(PermissionDenied):
        registro["richiedi_squadra"].anteprima(contesto, team="lead-crm-adabox", settimane=4)
    with pytest.raises(PermissionDenied):
        registro["catalogo_agenti"].funzione(contesto)


def test_strumenti_dell_assunzione_mai_agli_agenti(client, collegato, ammesse):
    for nome in ("catalogo_agenti", "richiedi_squadra", "stato_richieste_agenti"):
        OperazioneAmmessa.objects.create(strumento=nome)
    assert not {"catalogo_agenti", "richiedi_squadra", "stato_richieste_agenti"} & set(operazioni.esponibili())
    nomi = {t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert "cerca_record" in nomi and not nomi & {"catalogo_agenti", "richiedi_squadra", "stato_richieste_agenti"}
