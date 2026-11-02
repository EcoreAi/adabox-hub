"""L'area «Agenti AI»: negozio, scheda, Assumi su una pagina sola, richieste come un ordine, i miei agenti, avanzate."""
import datetime
import hashlib
import re

import pytest
from django.contrib.auth.models import Permission, User
from django.utils import timezone

from awf import fabbrica
from awf.models import Agente, Approvazione, Chiamata, Collegamento, OperazioneAmmessa, RichiestaAgenti

from .conftest import ingaggio
from .test_mcp import rpc
from .test_richieste import FORGE, SQUADRA, STATO, _stato, cache_pulita, fabbrica_nota, listino  # noqa: F401

VETRINA = {"icon": "🎯", "tagline": "Qualifica le richieste nuove ogni mattina",
           "benefits": ["I commerciali chiamano prima chi conta", "Nessun lead dimenticato", "Opportunità in ordine",
                        "Quarto vantaggio"],
           "day": [{"time": "07:30", "text": "Legge le richieste arrivate dal sito"}],
           "never": ["Non promette prezzi né sconti"],
           "faq": [{"q": "Vede le mie fatture?", "a": "No: solo le Opportunità."}]}
ALTRA = {**SQUADRA, "slug": "ordini-vendite", "name": "Ordini", "department": "vendite",
         "description": "Segue gli ordini.", "operations": [{"tool": "awf.cerca_record", "view": "zoo.animali",
                                                             "effect": "read"}]}
PAROLE_TECNICHE = ("MCP", "bearer", "wfc_", "prefisso", "ingaggio", "osservazione")


@pytest.fixture
def vetrina(listino):
    listino.risposte["/api/catalog"] = (200, {"teams": [{**SQUADRA, "showcase": VETRINA}, ALTRA]})
    return listino


def _primari(pagina):
    return len(re.findall(r'class="ui-btn ui-btn-primary', pagina.split('<div class="ui-pagehead">', 1)[1]))


# ---------- menu del profilo: niente link in testata ----------

def test_voce_nel_profilo_solo_per_chi_gestisce(client, superuser, utente, listino):
    r = client.get("/awf/negozio/")
    assert "Agenti AI" in [v["label"] for v in r.context["voci_profilo"]]
    assert not {"Agentic Workforce", "Agenti", "Agate"} & {v["label"] for v in r.context["theme"]["nav"]}
    client.force_login(utente)
    pagina = client.get("/dashboard/").content.decode()
    assert "Agenti AI" not in pagina and "Controllo AI" not in pagina
    amministratore = User.objects.create_user("anna", "a@example.com", "pass12345!")
    amministratore.user_permissions.add(Permission.objects.get(content_type__app_label="awf",
                                                               codename="change_collegamento"))
    client.force_login(amministratore)
    pagina = client.get("/dashboard/").content.decode()
    assert '<svg><use href="#icon-users"/></svg> Agenti AI' in pagina and "Controllo AI" not in pagina
    assert pagina.index("Cambia password") < pagina.index("Agenti AI") < pagina.index("Esci")


# ---------- negozio ----------

def test_negozio_con_vetrina_e_reparti(client, superuser, vetrina):
    pagina = client.get("/awf/negozio/").content.decode()
    assert "🎯" in pagina and "Qualifica le richieste nuove ogni mattina" in pagina
    assert "I commerciali chiamano prima chi conta" in pagina and "Opportunità in ordine" in pagina
    assert "Quarto vantaggio" not in pagina                                          # al più 3 nella scheda breve
    assert "3 giorni di prova" in pagina and "da 150 €/settimana" in pagina
    assert 'href="/awf/negozio/lead-crm-adabox/"' in pagina and 'href="/awf/assumi/lead-crm-adabox/"' in pagina
    assert ">CRM</a>" in pagina and ">Vendite</a>" in pagina and "Ordini" in pagina   # gettoni dei reparti
    filtrata = client.get("/awf/negozio/?reparto=vendite").content.decode()
    assert "Ordini" in filtrata and "Lead e CRM" not in filtrata
    for parola in PAROLE_TECNICHE:
        assert parola not in pagina, parola


def test_negozio_senza_vetrina_ricava_dal_catalogo(client, superuser, listino):
    pagina = client.get("/awf/negozio/").content.decode()
    assert "Qualifica i lead e tiene in ordine le opportunità" in pagina             # la prima frase
    assert "Qualificatore lead: Dà un punteggio ai lead" in pagina                   # dai ruoli


def test_negozio_con_la_fabbrica_giu(client, superuser, finta, fabbrica_nota):
    finta.risposte["/api/catalog"] = (fabbrica.ErroreFabbrica("fabbrica non raggiungibile (URLError)"), {})
    r = client.get("/awf/negozio/")
    assert r.status_code == 200 and "La fabbrica non risponde, riprova tra poco" in r.content.decode()
    finta.risposte["/api/catalog"] = (503, {})
    assert "La fabbrica non risponde" in client.get("/awf/negozio/").content.decode()


def test_negozio_senza_indirizzo_lo_chiede(client, superuser, finta, monkeypatch):
    monkeypatch.delenv("AWF_FORGE_URL", raising=False)
    pagina = client.get("/awf/negozio/").content.decode()
    assert "Prima di iniziare" in pagina and 'name="forge_url"' in pagina and finta.richieste == []
    client.post("/awf/negozio/", {"azione": "fabbrica", "forge_url": "ftp://x"})
    assert Collegamento.attuale().forge_url == ""
    client.post("/awf/negozio/", {"azione": "fabbrica", "forge_url": FORGE + "/"})
    assert Collegamento.attuale().forge_url == FORGE


def test_negozio_vuoto(client, superuser, finta, fabbrica_nota):
    finta.risposte["/api/catalog"] = (200, {"teams": []})
    assert "Il negozio è vuoto per ora" in client.get("/awf/negozio/").content.decode()


# ---------- scheda dell'agente ----------

def test_scheda_con_tutte_le_sezioni_e_il_calcolo(client, superuser, vetrina):
    pagina = client.get("/awf/negozio/lead-crm-adabox/").content.decode()
    for titolo in ("Cosa fa per te", "Una giornata tipo", "Cosa può fare", "Cosa non farà mai", "Quali dati vede",
                   "Quanto costa", "Domande frequenti"):
        assert titolo in pagina, titolo
    assert "07:30" in pagina and "Legge le richieste arrivate dal sito" in pagina
    assert "Leggere: Opportunità" in pagina and "Modificare: Opportunità — Cambia priorità e probabilità" in pagina
    assert "Eliminare: Opportunità (irreversibile) — Toglie i doppioni" in pagina and "con il tuo ok" in pagina
    assert "Non promette prezzi né sconti" in pagina and "niente password" in pagina
    assert "Vede soltanto: <strong>Opportunità</strong>" in pagina and "Vede le mie fatture?" in pagina
    assert '<strong id="stima">600 €</strong>' in pagina                            # 4 settimane: 150 × 4
    assert "consumo AI con ricarico 40%" in pagina and "credito iniziale di 30 €" in pagina
    assert "I primi 3 giorni sono di prova" in pagina and 'data-periodo="150" data-giorni="7"' in pagina
    assert "awf.lancia_razzi" not in pagina and "Non disponibile in questa versione" in pagina
    pagina = client.get("/awf/negozio/lead-crm-adabox/?settimane=3").content.decode()
    assert '<strong id="stima">450 €</strong>' in pagina
    pagina = client.get("/awf/negozio/lead-crm-adabox/?settimane=99").content.decode()
    assert '<strong id="stima">7800 €</strong>' in pagina                           # al più 52 settimane
    assert client.get("/awf/negozio/inesistente/").status_code == 404


def test_scheda_senza_vetrina_e_app_mancante(client, superuser, vetrina):
    pagina = client.get("/awf/negozio/ordini-vendite/").content.decode()
    assert "Chi c'è nella squadra" in pagina and "Qualificatore lead" in pagina
    assert "Chi decide cosa può fare?" in pagina                                     # domande di base
    assert "l'app «zoo»" in pagina and "non è installata" in pagina


# ---------- Assumi: una pagina sola, già compilata ----------

URL = "/awf/assumi/lead-crm-adabox/"
PASSWORD = {"password": "pass12345!"}                                                 # quella di `superuser`
PERSONALIZZATA = {"settimane": 6, "note": "circa 10 richieste al giorno", "reparto": "Vendite",
                  "op-0": "mai", "op-1": "mai", "op-2": "ok", **PASSWORD}
APERTA = '<details class="ui-card is-revealed ui-section" open'


@pytest.fixture
def persone(db):
    mario = User.objects.create_user("mario.r", "mr@example.com", "x", first_name="Mario", last_name="Rossi")
    anna = User.objects.create_user("anna.b", "ab@example.com", "x", first_name="Anna", last_name="Bianchi")
    User.objects.create_user("spento", "s@example.com", "x", is_active=False)
    return mario, anna


def test_cassa_gia_compilata(client, superuser, vetrina, persone, collegato):
    pagina = client.get(URL).content.decode()
    assert "Riepilogo" in pagina and "Cosa succede adesso" in pagina and _primari(pagina) == 1
    assert '<button class="ui-btn ui-btn-primary ui-btn-lg" type="submit">Conferma</button>' in pagina
    assert "Personalizza" in pagina and "<details" in pagina and APERTA not in pagina   # chiusa: tutto già scelto
    assert 'value="4"' in pagina and "600 €" in pagina and "3 giorni" in pagina      # 4 settimane proposte
    assert f'<option value="{superuser.pk}" selected>' in pagina                       # lo segue chi chiede
    assert "Mario Rossi" in pagina and "Anna Bianchi" in pagina
    assert "spento" not in pagina and "awf-buyer" not in pagina and ">Buyer<" not in pagina   # mai gli agenti
    assert "Serve per lavorare: sempre sì." in pagina and 'name="op-1" value="si" checked' in pagina
    assert 'name="op-2" value="ok" checked' in pagina and "non disponibile" in pagina
    assert "<strong>Sì</strong> <span class=\"ui-help\">(lo fa da solo)</span>" in pagina
    assert "<strong>Con il tuo ok</strong>" in pagina and "<strong>Mai</strong>" not in pagina
    assert 'name="persone" value' in pagina and " checked>Mario" not in pagina     # nessuna persona
    for parola in (*PAROLE_TECNICHE, "in Agate"):
        assert parola not in pagina, parola


def test_errori_tengono_quello_che_hai_scritto(client, superuser, vetrina, persone):
    r = client.post(URL, {**PERSONALIZZATA, "settimane": 0, "responsabile": 99999})
    pagina = r.content.decode()
    assert r.status_code == 200 and "Un numero da 1 a 52" in pagina and "Scegli chi segue gli agenti" in pagina
    assert APERTA in pagina and 'value="Vendite"' in pagina
    assert 'name="op-1" value="mai" checked' in pagina and not RichiestaAgenti.objects.exists()


def test_conferma_con_i_valori_proposti(client, superuser, vetrina):
    r = client.post(URL, PASSWORD)
    rich = RichiestaAgenti.objects.get()
    assert r.status_code == 302 and r["Location"] == f"/awf/richieste/{rich.pk}/"
    corpo = next(x for x in vetrina.richieste if x["url"].endswith("/api/hire-requests"))["corpo"]
    assert corpo["weeks"] == 4 and corpo["notes"] == "Lavora per: responsabile root."
    assert rich.responsabile == superuser and not rich.persone.exists() and rich.settimane == 4
    assert rich.scelte == {"cerca_record|crm.opportunita": "si", "modifica_record|crm.opportunita": "si",
                           "elimina_record|crm.opportunita": "ok", "lancia_razzi|": "ok"}
    assert set(OperazioneAmmessa.objects.filter(attiva=True, vista="crm.opportunita").values_list(
        "strumento", flat=True)) == {"cerca_record", "modifica_record", "elimina_record"}


def test_conferma_personalizzata_prepara_adabox_e_segue_il_contratto(client, superuser, vetrina, persone):
    from agate.models import Collegamento as CollegamentoAgate
    CollegamentoAgate.objects.create(gateway_url="https://api.agate.esempio.it",
                                     console_url="https://console.agate.esempio.it")
    mario, anna = persone
    r = client.post(URL, {**PERSONALIZZATA, "responsabile": mario.pk, "persone": [anna.pk, 99999]})
    assert r.status_code == 302 and r["Location"] == f"/awf/richieste/{RichiestaAgenti.objects.get().pk}/"
    corpo = next(x for x in vetrina.richieste if x["url"].endswith("/api/hire-requests"))["corpo"]
    assert {k: corpo[k] for k in ("team", "team_version", "weeks")} == {"team": "lead-crm-adabox", "team_version": 1,
                                                                        "weeks": 6}
    assert corpo["notes"] == ("circa 10 richieste al giorno\nLavora per: reparto Vendite; responsabile Mario Rossi; "
                              "passa il lavoro a Anna Bianchi.")
    assert set(corpo["company"]) == {"name", "vat", "email", "contact"} and corpo["plugin"]["kind"] == "django"
    assert corpo["agate"] == {"gateway_url": "https://api.agate.esempio.it",
                              "console_url": "https://console.agate.esempio.it"}
    dichiarate = {o["name"] for o in corpo["plugin"]["operations"]}
    assert "elimina_record" in dichiarate and "modifica_record" not in dichiarate   # ammesse prima dell'invio
    voci = set(OperazioneAmmessa.objects.filter(attiva=True).values_list("strumento", "vista"))
    assert {("cerca_record", "crm.opportunita"), ("elimina_record", "crm.opportunita")} <= voci
    assert not OperazioneAmmessa.objects.filter(strumento__in=["modifica_record", "lancia_razzi"]).exists()
    rich = RichiestaAgenti.objects.get()
    assert rich.scelte["modifica_record|crm.opportunita"] == "mai"
    assert rich.scelte["elimina_record|crm.opportunita"] == "ok" and rich.scelte["cerca_record|crm.opportunita"] == "si"
    assert rich.responsabile == mario and list(rich.persone.all()) == [anna] and rich.reparto_azienda == "Vendite"


def test_conferma_rifiutata_non_lascia_nulla(client, superuser, vetrina, persone):
    vetrina.risposte["/api/hire-requests"] = (409, {"detail": "no"})
    r = client.post(URL, {**PERSONALIZZATA, "responsabile": persone[0].pk})
    pagina = r.content.decode()
    assert r.status_code == 200 and "è cambiata" in pagina and "Non è cambiato nulla" in pagina
    assert 'value="Vendite"' in pagina                                               # si riprova senza riscrivere
    assert not RichiestaAgenti.objects.exists() and not OperazioneAmmessa.objects.filter(
        strumento="elimina_record").exists()


# ---------- richieste: il contratto passo per passo, un solo bottone principale ----------

@pytest.fixture
def inviata(client, superuser, vetrina, persone):
    client.post(URL, {**PERSONALIZZATA, "responsabile": persone[0].pk, "persone": [persone[1].pk]})
    return RichiestaAgenti.objects.get()


def test_tappe_e_un_solo_bottone(client, inviata, vetrina):
    vetrina.risposte[STATO] = _stato("received")
    pagina = client.get("/awf/richieste/").content.decode()
    assert 'class="is-attuale" aria-current="step">Richiesta inviata' in pagina
    assert "Un passaggio da fare una volta sola." in pagina and _primari(pagina) == 1
    assert 'href="/agate/impostazioni/">Collega il Controllo AI' in pagina and "Ritira la richiesta" in pagina
    for parola in PAROLE_TECNICHE:
        assert parola not in pagina, parola

    Collegamento.objects.filter(pk=1).update(mcp_impronta="a" * 64)
    assert _primari(client.get("/awf/richieste/").content.decode()) == 0               # si aspetta Agentlia

    RichiestaAgenti.objects.filter(pk=inviata.pk).update(
        stato="da_approvare", letta_il=timezone.now(), approve_url="https://console.agate.esempio.it/e/1/")
    pagina = client.get("/awf/richieste/").content.decode()
    assert 'class="is-attuale" aria-current="step">Contratto pronto' in pagina and _primari(pagina) == 1
    assert 'href="https://console.agate.esempio.it/e/1/" target="_blank" rel="noopener">Conferma il contratto' \
        in pagina and "Ritira la richiesta" not in pagina and "una conferma e il contratto parte" in pagina

    domani = (timezone.now() + datetime.timedelta(days=1)).isoformat()
    vetrina.risposte[STATO] = _stato("connected", plugin_token="wpt_" + "p" * 40, install_id="ins_9",
                                     engagement=ingaggio(observe_until=domani))
    fabbrica.aggiorna(RichiestaAgenti.objects.get())
    pagina = client.get("/awf/richieste/").content.decode()
    assert 'class="is-attuale" aria-current="step">Periodo di prova' in pagina and _primari(pagina) == 1
    assert 'href="/awf/miei/">Vedi i tuoi agenti' in pagina

    Collegamento.objects.filter(pk=1).update(ultimo_stato=ingaggio())
    pagina = client.get("/awf/richieste/").content.decode()
    assert 'class="is-attuale" aria-current="step">Al lavoro' in pagina


def test_collegata_senza_collegamento_ad_agate(client, inviata, vetrina):
    vetrina.risposte[STATO] = _stato("connected", plugin_token="wpt_" + "p" * 40, install_id="ins_9",
                                     engagement=ingaggio())
    fabbrica.aggiorna(inviata)
    pagina = client.get("/awf/richieste/").content.decode()
    assert _primari(pagina) == 1 and "Collega il Controllo AI" in pagina


# ---------- i miei agenti ----------

def test_nessun_agente(client, superuser, listino):
    pagina = client.get("/awf/miei/").content.decode()
    assert "Non hai ancora agenti" in pagina and 'href="/awf/negozio/">Vai al Negozio' in pagina


@pytest.fixture
def al_lavoro(client, inviata, vetrina):
    vetrina.risposte[STATO] = _stato("connected", plugin_token="wpt_" + "p" * 40, install_id="ins_9",
                                     engagement=ingaggio())
    vetrina.risposte["/api/plugins/heartbeat"] = (200, {"engagement": ingaggio()})
    fabbrica.aggiorna(inviata)
    Collegamento.objects.filter(pk=1).update(mcp_impronta="a" * 64)
    inviata.refresh_from_db()
    return inviata


def test_i_miei_agenti_con_i_conti_di_oggi(client, al_lavoro):
    buyer = Agente.objects.get(nome="Buyer")
    for effetto, esito in [("read", "eseguita"), ("read", "eseguita"), ("write", "eseguita"), ("write", "rifiutata")]:
        Chiamata.objects.create(agente=buyer, strumento="x", effetto=effetto, esito=esito)
    vecchia = Chiamata.objects.create(agente=buyer, strumento="x", effetto="read", esito="eseguita")
    Chiamata.objects.filter(pk=vecchia.pk).update(creato=timezone.now() - datetime.timedelta(days=2))
    for n in range(2):
        Approvazione.objects.create(approval_id=f"apr_{n}", riepilogo="Togli un doppione")
    r = client.get("/awf/miei/")
    pagina = r.content.decode()
    conti = {x["a"].nome: x for x in r.context["agenti"]}
    assert set(conti) == {"Buyer", "Magazziniere"}
    assert (conti["Buyer"]["letture"], conti["Buyer"]["modifiche"], conti["Buyer"]["rifiutate"]) == (2, 1, 1)
    assert conti["Magazziniere"]["letture"] == 0 and r.context["in_attesa"] == 2
    assert "al lavoro" in pagina and "5 giorni rimasti" in pagina and "Mario Rossi" in pagina
    assert "Anna Bianchi" in pagina and "Metti in pausa · Rinnova · Disdici" in pagina
    assert "https://agate.esempio.it/console/engagements/eng_1/" in pagina
    assert "https://agate.esempio.it/console/approvals/" in pagina
    assert f"/awf/miei/{al_lavoro.pk}/cosa-puo-fare/" in pagina and f"/awf/miei/{al_lavoro.pk}/persone/" in pagina


def test_cambia_cosa_puo_fare(client, al_lavoro):
    url = f"/awf/miei/{al_lavoro.pk}/cosa-puo-fare/"
    pagina = client.get(url).content.decode()
    assert 'name="op-1" value="mai" checked' in pagina and 'name="op-2" value="ok" checked' in pagina
    client.post(url, {"op-1": "si", "op-2": "mai"})
    al_lavoro.refresh_from_db()
    assert al_lavoro.scelte["modifica_record|crm.opportunita"] == "si"
    assert al_lavoro.scelte["elimina_record|crm.opportunita"] == "mai"
    assert OperazioneAmmessa.objects.get(strumento="modifica_record").attiva
    assert not OperazioneAmmessa.objects.get(strumento="elimina_record").attiva
    buyer = User.objects.get(username="awf-buyer")
    assert buyer.has_perm("crm.change_opportunita") and not buyer.has_perm("crm.delete_opportunita")
    assert "/api/plugins/heartbeat" in fabbrica.trasporto.richieste[-1]["url"]       # la versione dichiarata cambia


def test_cambia_persone(client, al_lavoro, persone):
    mario, anna = persone
    url = f"/awf/miei/{al_lavoro.pk}/persone/"
    assert 'value="Vendite"' in client.get(url).content.decode()
    client.post(url, {"reparto": "Assistenza", "responsabile": anna.pk, "persone": [mario.pk]})
    al_lavoro.refresh_from_db()
    assert al_lavoro.reparto_azienda == "Assistenza" and al_lavoro.responsabile == anna
    assert list(al_lavoro.persone.all()) == [mario]
    RichiestaAgenti.objects.filter(pk=al_lavoro.pk).update(stato="ritirata")
    assert client.get(url).status_code == 404


# ---------- avanzate ----------

def test_avanzate_chiave_per_agate_una_volta(client, inviata):
    pagina = client.get("/awf/avanzate/").content.decode()
    assert "Collega adabox ad Agate (una volta sola)" in pagina and "da fare" in pagina
    for pagina_tecnica in ("/awf/stato/", "/awf/operazioni/", "/awf/approvazioni/", "/awf/agenti/"):
        assert pagina_tecnica in pagina
    pagina = client.post("/awf/avanzate/", {"azione": "bearer"}).content.decode()
    bearer = next(p for p in pagina.split("<code>") if p.startswith("awf_")).split("</code>")[0]
    assert "https://erp.esempio.it/awf/mcp/" in pagina and "Applicazione dell'azienda (server MCP)" in pagina
    assert "<code>awf</code>" in pagina
    assert Collegamento.attuale().mcp_impronta == hashlib.sha256(bearer.encode()).hexdigest()
    seguente = client.get("/awf/avanzate/").content.decode()
    assert bearer not in seguente and "Genera una chiave nuova" in seguente and "fatto" in seguente
    assert rpc(client, "tools/list", bearer=bearer).status_code == 200


def test_avanzate_senza_indirizzo_lo_chiede(client, superuser, finta):
    pagina = client.get("/awf/avanzate/").content.decode()
    assert 'name="base_url"' in pagina
    client.post("/awf/avanzate/", {"azione": "bearer"})
    assert Collegamento.attuale().mcp_impronta == ""
    client.post("/awf/avanzate/", {"azione": "base_url", "base_url": "https://erp.esempio.it"})
    assert Collegamento.attuale().base_url == "https://erp.esempio.it"


def test_pagine_tecniche_nella_scheda_avanzate(client, superuser, collegato, finta):
    finta.risposte["/api/plugins/heartbeat"] = (200, {"engagement": ingaggio()})
    r = client.get("/awf/stato/")
    attive = [v["label"] for v in r.context["menu_app"] if v["attiva"]]
    assert attive == ["Avanzate"] and r.context["app_corrente"]["label"] == "Agenti AI"
