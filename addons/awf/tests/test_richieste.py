import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied

from awf import fabbrica, lavori, operazioni, squadre
from awf.models import Agente, Collegamento, OperazioneAmmessa, RichiestaAgenti
from core.models import Azienda

from .conftest import AGENTI, ingaggio
from .test_mcp import rpc

FORGE = "https://fabbrica.esempio.it"
SQUADRA = {
    "slug": "lead-crm-adabox", "version": 1, "name": "Lead e CRM", "department": "crm",
    "description": "Qualifica i lead e tiene in ordine le opportunità. Lavora ogni mattina.", "kind": "django",
    "saas": "adabox", "observe_days": 3,
    "members": [{"role": "adabox.crm.qualifier", "name": "Qualificatore lead", "position": "single",
                 "kind": "conversational", "description": "Dà un punteggio ai lead"}],
    "operations": [{"tool": "awf.cerca_record", "view": "crm.opportunita", "effect": "read", "risk": "low",
                    "line": ""},
                   {"tool": "awf.modifica_record", "view": "crm.opportunita", "effect": "write", "risk": "medium",
                    "line": "Cambia priorità e probabilità"},
                   {"tool": "awf.elimina_record", "view": "crm.opportunita", "effect": "irreversible",
                    "risk": "high", "line": "Toglie i doppioni"},
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
    squadre_ = fabbrica.catalogo()
    assert [s["slug"] for s in squadre_] == ["lead-crm-adabox"]                    # quella non valida resta fuori
    assert squadre_[0]["operazioni"][1] == {"tool": "awf.modifica_record", "view": "crm.opportunita",
                                            "effect": "write", "risk": "medium", "line": "Cambia priorità e probabilità"}
    assert squadre_[0]["vetrina"] == {}                                             # vetrina facoltativa
    fabbrica.catalogo()
    fabbrica.catalogo("CRM")
    url = [r["url"] for r in listino.richieste]
    assert url == [f"{FORGE}/api/catalog?kind=django&saas=adabox",
                   f"{FORGE}/api/catalog?kind=django&saas=adabox&department=crm"]
    assert "Authorization" not in listino.richieste[0]["intestazioni"]                # pubblico


def test_vetrina_controllata(finta, fabbrica_nota):
    vetrina = {"icon": "🎯", "tagline": "Qualifica le richieste nuove", "benefits": ["Uno", 3, "Due"] + ["x"] * 9,
               "day": [{"time": "07:30", "text": "Legge le richieste"}, {"time": "domani", "text": "Ora strana"},
                       {"time": "08:00"}, "non un dizionario"],
               "never": ["Non promette sconti"], "faq": [{"q": "Vede le fatture?", "a": "No."}, {"q": "Senza risposta"}]}
    finta.risposte["/api/catalog"] = (200, {"teams": [{**SQUADRA, "showcase": vetrina}]})
    v = fabbrica.catalogo()[0]["vetrina"]
    assert v["icona"] == "🎯" and v["slogan"] == "Qualifica le richieste nuove"
    assert v["vantaggi"] == ["Uno", "Due", "x", "x"]                                  # al più 5, solo testi
    assert v["giornata"] == [{"ora": "07:30", "testo": "Legge le richieste"}, {"ora": "", "testo": "Ora strana"}]
    assert v["mai"] == ["Non promette sconti"] and v["domande"] == [{"domanda": "Vede le fatture?", "risposta": "No."}]


def test_catalogo_vecchio_url_porta_al_negozio(client, superuser, listino):
    r = client.get("/awf/catalogo/?reparto=crm")
    assert r.status_code == 302 and r["Location"] == "/awf/negozio/?reparto=crm"


def test_pagine_nuove_solo_per_chi_gestisce_awf(client, utente):
    client.force_login(utente)
    for url in ("/awf/negozio/", "/awf/negozio/lead-crm-adabox/", "/awf/assumi/lead-crm-adabox/", "/awf/richieste/",
                "/awf/miei/", "/awf/miei/1/cosa-puo-fare/", "/awf/miei/1/persone/", "/awf/avanzate/"):
        assert client.get(url).status_code == 403, url


# ---------- richiesta ----------

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
    assert c.mcp_impronta == "a" * 64                         # il bearer già dato ad Agate resta: è di adabox
    assert {a.nome for a in Agente.objects.filter(attivo=True, tecnico=False)} == {a["name"] for a in AGENTI}

    letture = len(listino.richieste)
    assert lavori.richieste() == "nessuna richiesta aperta"                          # chiusa: non si legge più
    assert len(listino.richieste) == letture


def test_collegata_senza_token_non_torna_indietro(listino):
    r = _richiesta()
    listino.risposte[STATO] = _stato("connected")
    fabbrica.aggiorna(r)
    assert r.stato == "collegata" and r.collegata_il is None and "codice di collegamento" in r.messaggio
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
    assert 'value="ritira"' in pagina and "Ritira la richiesta" in pagina
    client.post("/awf/richieste/", {"pk": r.pk, "azione": "ritira"})
    r.refresh_from_db()
    assert r.stato == "ritirata" and listino.richieste[-1]["metodo"] == "DELETE"
    assert listino.richieste[-1]["intestazioni"]["Authorization"] == "Bearer wfr_" + "r" * 40
    r.stato = "da_approvare"
    r.save()
    with pytest.raises(fabbrica.ErroreFabbrica, match="console di Agate"):
        fabbrica.ritira(r)


# ---------- cosa può fare: le scelte diventano operazioni ammesse ----------

def test_scelte_proposte_e_applicate(listino, superuser):
    righe = squadre.righe_operazioni(fabbrica.squadra(SQUADRA["slug"])["operazioni"])
    per_strumento = {x["strumento"]: x for x in righe}
    assert per_strumento["cerca_record"]["lettura"] and per_strumento["cerca_record"]["proposta"] == "si"
    assert per_strumento["modifica_record"]["proposta"] == "si"
    assert per_strumento["elimina_record"]["proposta"] == "ok"                       # irreversibile: con il tuo ok
    assert per_strumento["lancia_razzi"]["stato"] == squadre.NON_DISPONIBILE
    # le letture restano sì anche se qualcuno manda «mai»
    scelte = squadre.scelte(righe, {"cerca_record|crm.opportunita": "mai", "modifica_record|crm.opportunita": "mai",
                                    "elimina_record|crm.opportunita": "boh"})
    assert scelte["cerca_record|crm.opportunita"] == "si" and scelte["modifica_record|crm.opportunita"] == "mai"
    assert scelte["elimina_record|crm.opportunita"] == "ok"
    squadre.applica(righe, scelte, superuser)
    voci = dict(OperazioneAmmessa.objects.values_list("strumento", "attiva"))
    assert voci == {"cerca_record": True, "elimina_record": True}
    buyer_perm = operazioni.permessi_derivati().values_list("codename", flat=True)
    assert "delete_opportunita" in buyer_perm and "change_opportunita" not in buyer_perm
    # cambio idea: «mai» spegne, «sì» riaccende, niente doppioni
    righe = squadre.righe_operazioni(fabbrica.squadra(SQUADRA["slug"])["operazioni"])
    nuove, spente = squadre.applica(righe, {"elimina_record|crm.opportunita": "mai",
                                            "modifica_record|crm.opportunita": "si"})
    assert [x["strumento"] for x in nuove] == ["modifica_record"] and [x["strumento"] for x in spente] == [
        "elimina_record"]
    assert not OperazioneAmmessa.objects.get(strumento="elimina_record").attiva
    assert OperazioneAmmessa.objects.filter(strumento="modifica_record").count() == 1


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
    assert "credito prepagato 42 € (30 € al costo del provider)" in testo and '"giorni_di_prova": 3' in testo
    assert "/awf/negozio/lead-crm-adabox/" in testo and "Qualifica i lead" in testo


def test_assistente_propone_e_alla_conferma_chiede_la_squadra(scena):
    from ai.models import Proposta
    finta = scena["finta"]
    risultato = _turno(scena, [("richiedi_squadra", {"team": "lead-crm-adabox", "settimane": 4,
                                                     "note": "CRM, circa 10 opportunità al giorno"})])[0]
    assert not risultato["errore"] and "NON è ancora eseguita" in risultato["contenuto"]
    p = Proposta.objects.get()
    assert p.strumento == "richiedi_squadra" and p.rischio == "scrittura" and "Lead e CRM" in p.titolo
    assert p.url == "/awf/negozio/lead-crm-adabox/"                                  # la scheda dell'agente
    dettagli = {d["campo"]: d["dopo"] for d in p.dettagli}
    assert dettagli["Costo fisso stimato"] == "600 €" and "credito iniziale 42 € (30 € al costo" in dettagli["Modelli AI"]
    assert "costo del provider + 40%" in dettagli["Modelli AI"]
    assert "periodo di prova" in dettagli["Prova"] and "osservazione" not in str(p.dettagli)
    assert "conferma il contratto" in dettagli["Poi"] and dettagli["Durata"] == "4 settimane"
    assert not [x for x in finta.richieste if x["metodo"] == "POST"] and not RichiestaAgenti.objects.exists()

    r = scena["client"].post(f"/ai/proposta/{p.pk}/conferma/", {}, HTTP_HX_REQUEST="true")
    p.refresh_from_db()
    assert r.status_code == 200 and p.stato == "eseguita" and p.url == "/awf/richieste/"
    assert "Prossimi passi" in p.esito and "Agenti AI → Richieste" in p.esito
    invio = next(x for x in finta.richieste if x["metodo"] == "POST")
    assert invio["corpo"]["weeks"] == 4 and invio["corpo"]["notes"] == "CRM, circa 10 opportunità al giorno"
    rich = RichiestaAgenti.objects.get()
    assert rich.creata_da == scena["capo"] and rich.azienda_id == 1
    # adabox si è preparato da solo con le scelte proposte, e la richiesta lo dichiara alla fabbrica
    assert set(OperazioneAmmessa.objects.filter(vista="crm.opportunita").values_list("strumento", flat=True)) == {
        "cerca_record", "modifica_record", "elimina_record"}
    assert {"modifica_record", "elimina_record"} <= {o["name"] for o in invio["corpo"]["plugin"]["operations"]}

    finta.risposte[STATO] = _stato("proposed", approve_url="https://console.agate.esempio.it/console/engagements/e/")
    stato = _turno(scena, [("stato_richieste_agenti", {})], testo="A che punto siamo?")[0]
    assert not stato["errore"] and "Contratto da approvare in Agate" in stato["contenuto"]
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
