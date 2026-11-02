"""Agate incluso (§8.6): l'azienda senza Agate assume il primo agente e la conferma fa tutto da sola — la fabbrica apre
il suo Agate, adabox si collega con il codice ricevuto, parte la richiesta e il contratto si approva da solo. Poi
«Da approvare» in frasi semplici e «Cosa fa» come elenco."""
import datetime
import html
import json
import re

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from agate import cliente
from agate.models import Collegamento as CollegamentoAgate
from awf import fabbrica, frasi
from awf.models import Agente, Approvazione, Collegamento, OperazioneAmmessa, RichiestaAgenti
from core.models import Azienda

from .test_negozio import PASSWORD, URL, vetrina  # noqa: F401
from .test_richieste import SQUADRA, STATO, _stato, cache_pulita, fabbrica_nota, listino  # noqa: F401

INCLUSO = "/api/agate/included"
CODICE, CODICE_NUOVO = "agc_" + "c" * 32, "agc_" + "n" * 32
GATEWAY, CONSOLE = "https://agate.agentlia.it", "https://console.agentlia.it"
APERTO = (201, {"app_code": CODICE, "gateway_url": GATEWAY, "console_url": CONSOLE + "/", "tenant": "Adabox Srl"})
FATTORIA = "agf_" + "f" * 32
PROVA = "/awf/agate-incluso/prova/"


class AgateFinto:
    """Il gateway dell'Agate appena aperto: `/v1/apps/connect` (§8.1) e `/v1/approvals/{id}/decide` (§8.4)."""

    def __init__(self):
        self.chiamate = []
        self.collega = [(201, {"tenant": "Adabox Srl", "environment": "production", "console_url": CONSOLE,
                               "gateway_url": GATEWAY,
                               "keys": {"evaluate": "agt_eval", "decide": "agt_decide", "sync": "agt_sync"},
                               "webhook_secret": "whsec_" + "w" * 40, "factory_code": FATTORIA,
                               "tools": {"imported": 3, "enabled": 3}})]

    def __call__(self, metodo, url, intestazioni, corpo):
        dati = json.loads(corpo) if corpo else None
        self.chiamate.append((metodo, url, intestazioni.get("Authorization", ""), dati))
        if url.endswith("/v1/apps/connect"):
            stato, risposta = self.collega.pop(0) if len(self.collega) > 1 else self.collega[0]
        elif url.endswith("/decide"):
            stato, risposta = 200, {"status": "approved"}
        elif url.endswith("/v1/apps/sync"):
            stato, risposta = 200, {"imported": 0, "updated": 1, "disabled": 0}
        else:
            stato, risposta = 404, {"title": "Rotta sconosciuta"}
        return stato, json.dumps(risposta).encode()


@pytest.fixture
def agate(monkeypatch):
    finto = AgateFinto()
    monkeypatch.setattr(cliente, "trasporto", finto)
    return finto


@pytest.fixture
def senza_agate(vetrina, agate, superuser):
    Azienda.objects.filter(pk=1).update(nome="Adabox Srl", partita_iva="IT01234567890")
    return vetrina


def _inviate(finta, percorso):
    return [x for x in finta.richieste if x["metodo"] == "POST" and x["url"].endswith(percorso)]


# ---------- la cassa: il Controllo AI è incluso ----------

def test_la_cassa_dice_che_agate_e_incluso(client, senza_agate):
    pagina = client.get(URL).content.decode()
    assert ("Il Controllo AI (Agate) è incluso: lo attiviamo noi alla conferma. Riceverai un invito a "
            "<strong>root@example.com</strong> per vedere il registro quando vuoi.") in pagina
    assert "Prima serve un passaggio" not in pagina and "passaggio tecnico" not in pagina
    assert 'name="email"' not in pagina and 'id="passi-incluso" hidden' in pagina
    assert "Apriamo il vostro Agate…" in pagina and "Colleghiamo adabox…" in pagina
    assert not _inviate(senza_agate, INCLUSO)                                       # si apre solo alla conferma


def test_con_un_agate_gia_noto_resta_il_codice(client, senza_agate):
    CollegamentoAgate.objects.create(gateway_url="https://api.agate.esempio.it")
    pagina = client.get(URL).content.decode()
    assert "è incluso" not in pagina and "Prima serve un passaggio da fare una volta sola" in pagina


def test_cosa_fa_in_elenco_per_scelta(client, senza_agate):
    pagina = client.get(URL).content.decode()
    riga = pagina.split("<th>Cosa fa</th>", 1)[1].split("</tr>", 1)[0]
    assert "<strong>Sì</strong>" in riga and "<strong>Con il tuo ok</strong>" in riga
    assert "<strong>Mai</strong>" not in riga                                       # nessuna «Mai» proposta
    assert riga.count("<li>") == 3 and "<li>Modificare: Opportunità — Cambia priorità e probabilità</li>" in riga
    assert "</li><li>" in riga and "Opportunità; " not in riga                      # niente riga unica con i «;»
    pagina = client.post(URL, {"op-1": "mai", "settimane": 0}).content.decode()
    riga = pagina.split("<th>Cosa fa</th>", 1)[1].split("</tr>", 1)[0]
    assert "<strong>Mai</strong>" in riga and "<li>Modificare: Opportunità — Cambia priorità e probabilità</li>" in \
        riga.split("<strong>Mai</strong>", 1)[1]


# ---------- conferma: apri → collega → chiedi ----------

def test_conferma_apre_agate_collega_adabox_e_chiede_il_contratto(client, senza_agate, agate, superuser):
    senza_agate.risposte[INCLUSO] = APERTO
    bearer_prima = Collegamento.attuale().mcp_impronta
    r = client.post(URL, PASSWORD)
    rich = RichiestaAgenti.objects.get()
    assert r.status_code == 302 and r["Location"] == f"/awf/richieste/{rich.pk}/"

    # (a) la fabbrica apre l'Agate dell'azienda, titolare chi conferma
    [aperto] = _inviate(senza_agate, INCLUSO)
    prova = aperto["corpo"]["app"].pop("proof")
    assert re.match(r"^prv_[A-Za-z0-9_-]{32}$", prova)
    assert aperto["corpo"] == {"company": {"name": "Adabox Srl", "vat": "IT01234567890", "email": "root@example.com",
                                           "contact": "root"},
                               "app": {"name": "adabox-hub", "prefix": "awf", "base_url": "https://erp.esempio.it"}}
    assert "Authorization" not in aperto["intestazioni"]
    assert Client().get(PROVA).status_code == 404                                    # letta: non c'è più
    # (b) adabox si collega con il codice ricevuto, come con un codice incollato (§8.1)
    [(metodo, url, chiave, corpo)] = [x for x in agate.chiamate if x[1].endswith("/v1/apps/connect")]
    assert url == GATEWAY + "/v1/apps/connect" and chiave == "" and corpo["code"] == CODICE
    assert corpo["app"]["prefix"] == "awf" and corpo["app"]["mcp_url"] == "https://erp.esempio.it/awf/mcp/"
    assert corpo["app"]["webhook_url"] == "https://erp.esempio.it/agate/webhook/"
    a = CollegamentoAgate.attuale()
    assert a.incluso and a.modalita == CollegamentoAgate.ATTIVO and a.puo_decidere and a.gateway_url == GATEWAY
    assert a.console_url == CONSOLE and a.tenant == "Adabox Srl" and a.chiave_decide() == "agt_decide"
    c = Collegamento.attuale()
    assert c.mcp_impronta and c.mcp_impronta != bearer_prima and c.factory_code() == FATTORIA
    # (c) la richiesta parte con il codice per la fabbrica
    [invio] = _inviate(senza_agate, "/api/hire-requests")
    assert invio["corpo"]["agate"] == {"gateway_url": GATEWAY, "console_url": CONSOLE, "factory_code": FATTORIA}
    assert rich.consenso["agate_incluso"] is True and rich.consenso["email"] == "root@example.com"
    assert [x["url"].rsplit("/api/", 1)[1] for x in senza_agate.richieste if x["metodo"] == "POST"] == [
        "agate/included", "hire-requests"]

    senza_agate.risposte[STATO] = _stato("received")
    pagina = client.get(r["Location"]).content.decode()
    assert "Il Controllo AI (Agate) è attivo ✓: riceverai un invito a root@example.com" in pagina
    assert 'data-stato="fatto"' in pagina and "Apriamo il vostro Agate" in pagina
    assert '<li style="margin:2px 0" data-stato="attuale"><span aria-hidden="true">→</span> <strong>Chiediamo il ' \
           'contratto…</strong>' in pagina
    assert "Manca un passaggio" not in pagina

    # il contratto proposto combacia: adabox lo approva da solo, a nome di chi ha confermato
    proposta = {"team": SQUADRA["slug"], "team_version": 1, "weeks": 4, "observe_days": 3, "caps": SQUADRA["caps"],
                "price": SQUADRA["price"]}
    senza_agate.risposte[STATO] = _stato("proposed", approval_id="apr_contratto", proposal=proposta)
    rich = fabbrica.aggiorna(rich)
    assert rich.decisione == RichiestaAgenti.APPROVATA
    [(_, url, chiave, corpo)] = [x for x in agate.chiamate if x[1].endswith("/decide")]
    assert url == GATEWAY + "/v1/approvals/apr_contratto/decide" and chiave == "Bearer agt_decide"
    assert corpo["decision"] == "approved" and corpo["decided_by"] == "root <root@example.com>"
    assert "data-stato" not in client.get(f"/awf/richieste/{rich.pk}/").content.decode()   # i passi sono fatti

    pagina = client.get("/agate/impostazioni/").content.decode()
    assert ("Agate incluso, aperto per voi da Agentlia</strong> — console: <a class=\"ui-link\" "
            f"href=\"{CONSOLE}\"") in pagina
    assert "Agate incluso, aperto per voi da Agentlia — console:" in client.get("/agate/").content.decode()
    assert "è incluso" not in client.get(URL).content.decode()                     # ora è collegato


@pytest.mark.parametrize("stato, corpo, messaggio", [
    (409, {"detail": "app già collegata"}, "La vostra azienda ha già un Agate: collegatelo con il codice dalla sua "
                                           "console"),
    (422, {"detail": "email: obbligatoria"}, "Agentlia non ha accettato i dati dell'azienda: email: obbligatoria"),
    (429, {}, "Troppi tentativi in poco tempo: Agentlia ne accetta 3 l'ora, riprova più tardi"),
    (502, {}, "Il servizio che apre Agate non risponde in questo momento: riprova tra qualche minuto"),
    (500, {}, "Risposta inattesa di Agentlia (HTTP 500): riprova tra poco"),
    (fabbrica.ErroreFabbrica("fabbrica non raggiungibile (URLError)"), {},
     "Agentlia non risponde in questo momento: riprova tra poco"),
])
def test_agate_non_aperto_niente_a_meta_e_riprova(client, senza_agate, agate, stato, corpo, messaggio):
    senza_agate.risposte[INCLUSO] = (stato, corpo)    # un'eccezione: come il trasporto vero senza rete
    prima = Collegamento.attuale().mcp_impronta
    r = client.post(URL, PASSWORD)
    pagina = html.unescape(r.content.decode())
    assert r.status_code == 200 and "Non siamo riusciti ad attivare il Controllo AI." in pagina
    assert f"{messaggio}. Non è stata inviata nessuna richiesta e in adabox non è cambiato nulla" in pagina
    assert '<button class="ui-btn ui-btn-primary ui-btn-lg" type="submit">Riprova</button>' in pagina
    assert "Per riprovare, riscrivi la tua password" in pagina
    assert 'data-stato="errore"' in pagina and pagina.count('data-stato="futuro"') >= 2
    assert ('href="/agate/impostazioni/">Collega il vostro Agate con il codice' in pagina) == (stato == 409)
    assert 'href="/agate/impostazioni/">Collegatelo con un codice' in pagina or stato == 409   # il codice resta
    assert not RichiestaAgenti.objects.exists() and not CollegamentoAgate.objects.exists()
    assert not agate.chiamate and not _inviate(senza_agate, "/api/hire-requests")
    assert Collegamento.attuale().mcp_impronta == prima
    assert not OperazioneAmmessa.objects.filter(strumento="elimina_record").exists()

    senza_agate.risposte[INCLUSO] = APERTO             # Riprova: questa volta Agentlia lo apre
    r = client.post(URL, PASSWORD)
    assert r.status_code == 302 and RichiestaAgenti.objects.get().consenso["agate_incluso"]
    assert CollegamentoAgate.attuale().incluso


def test_servizio_non_attivo_torna_al_codice(client, senza_agate, agate):
    senza_agate.risposte[INCLUSO] = (503, {"detail": "Agate incluso non configurato"})
    r = client.post(URL, PASSWORD)
    rich = RichiestaAgenti.objects.get()
    assert r.status_code == 302 and "agate_incluso" not in rich.consenso           # come prima: la richiesta parte
    assert not CollegamentoAgate.objects.exists() and not agate.chiamate
    assert "agate" not in _inviate(senza_agate, "/api/hire-requests")[0]["corpo"]
    senza_agate.risposte[STATO] = _stato("received")
    pagina = html.unescape(client.get(r["Location"]).content.decode())
    assert "Manca un passaggio, una volta sola" in pagina and "Collega il Controllo AI" in pagina
    assert "Agate incluso non configurato: per questa volta il Controllo AI (Agate) non si attiva da solo" in pagina
    pagina = client.get(URL).content.decode()                                       # per un po' non si riprova
    assert "è incluso" not in pagina and "Prima serve un passaggio da fare una volta sola" in pagina
    RichiestaAgenti.objects.all().delete()
    client.post(URL, PASSWORD)
    assert len(_inviate(senza_agate, INCLUSO)) == 1
    cache.clear()
    assert "è incluso" in client.get(URL).content.decode()


def test_fabbrica_di_prima_senza_agate_incluso(client, senza_agate, agate):
    r = client.post(URL, PASSWORD)                     # 404: la rotta non c'è
    assert r.status_code == 302 and not CollegamentoAgate.objects.exists()
    assert "Prima serve un passaggio" in client.get(URL).content.decode()


def test_collegamento_non_riuscito_niente_a_meta_e_riprova(client, senza_agate, agate):
    senza_agate.risposte[INCLUSO] = [APERTO, (200, {**APERTO[1], "app_code": CODICE_NUOVO})]
    agate.collega = [(404, {"title": "Codice sconosciuto"}), *agate.collega]
    prima = Collegamento.attuale().mcp_impronta
    pagina = client.post(URL, PASSWORD).content.decode()
    assert "Il vostro Agate non ha accettato il codice per adabox: riprova, ne chiediamo uno nuovo." in pagina
    assert '<li style="margin:2px 0" data-stato="fatto"><span aria-hidden="true">✓</span> Apriamo il vostro Agate ' \
           in pagina and "<strong>Colleghiamo adabox</strong> <span class=\"ui-help\">non riuscito" in pagina
    assert not RichiestaAgenti.objects.exists() and not CollegamentoAgate.objects.exists()
    c = Collegamento.attuale()
    assert c.mcp_impronta == prima and not c.factory_code_cifrato                  # il bearer di prima, come prima

    r = client.post(URL, PASSWORD)                     # Riprova: un codice nuovo per lo stesso Agate (§8.6)
    assert r.status_code == 302 and len(_inviate(senza_agate, INCLUSO)) == 2
    codici = [x[3]["code"] for x in agate.chiamate if x[1].endswith("/v1/apps/connect")]
    assert codici == [CODICE, CODICE_NUOVO] and CollegamentoAgate.attuale().incluso


def test_adabox_non_raggiungibile_da_agate(client, senza_agate, agate):
    senza_agate.risposte[INCLUSO] = APERTO
    agate.collega = [(502, {"title": "MCP non raggiungibile"})]
    pagina = html.unescape(client.post(URL, PASSWORD).content.decode())
    assert ("Il vostro Agate non riesce a raggiungere adabox all'indirizzo https://erp.esempio.it/awf/mcp/: "
            "controlla che adabox sia raggiungibile da internet e riprova") in pagina
    assert not RichiestaAgenti.objects.exists()


def test_richiesta_rifiutata_dopo_agate_attivo(client, senza_agate, agate):
    senza_agate.risposte[INCLUSO] = APERTO
    senza_agate.risposte["/api/hire-requests"] = (429, {})
    pagina = client.post(URL, PASSWORD).content.decode()
    assert "Il Controllo AI è attivo ✓, ma la richiesta non è partita: troppe richieste" in pagina
    assert CollegamentoAgate.attuale().incluso and not RichiestaAgenti.objects.exists()
    assert "è incluso" not in pagina and '>Conferma</button>' in pagina            # ora si riprova solo la richiesta
    senza_agate.risposte["/api/hire-requests"] = (201, {"request_id": "r2", "token": "wfr_" + "r" * 40,
                                                         "status": "received"})
    assert client.post(URL, PASSWORD).status_code == 302
    assert len(_inviate(senza_agate, INCLUSO)) == 1                                 # Agate non si riapre


def test_email_chiesta_se_manca(client, senza_agate, agate, superuser):
    User.objects.filter(pk=superuser.pk).update(email="")
    pagina = client.get(URL).content.decode()
    assert 'name="email" type="email" required' in pagina and "all'email che scrivi qui sotto" in pagina
    pagina = client.post(URL, {**PASSWORD, "email": "non-una-email"}).content.decode()
    assert "Scrivi la tua email: lì arriva l&#x27;invito al Controllo AI (Agate)." in pagina
    assert 'value="non-una-email"' in pagina and not _inviate(senza_agate, INCLUSO)
    senza_agate.risposte[INCLUSO] = APERTO
    assert client.post(URL, {**PASSWORD, "email": "root@rossi.it"}).status_code == 302
    assert _inviate(senza_agate, INCLUSO)[0]["corpo"]["company"]["email"] == "root@rossi.it"
    superuser.refresh_from_db()
    assert superuser.email == "root@rossi.it" and RichiestaAgenti.objects.get().consenso["email"] == "root@rossi.it"


def test_email_non_salvata_se_agate_non_si_apre(client, senza_agate, agate, superuser):
    User.objects.filter(pk=superuser.pk).update(email="")
    senza_agate.risposte[INCLUSO] = (429, {})
    pagina = client.post(URL, {**PASSWORD, "email": "root@rossi.it"}).content.decode()
    assert 'value="root@rossi.it"' in pagina                                        # si riprova senza riscriverla
    superuser.refresh_from_db()
    assert superuser.email == ""


def test_agate_incluso_controlla_la_risposta(senza_agate, superuser):
    senza_agate.risposte[INCLUSO] = (201, {**APERTO[1], "app_code": "agc_corto"})
    with pytest.raises(fabbrica.ErroreFabbrica, match="codice valido"):
        fabbrica.agate_incluso(superuser, None, "https://erp.esempio.it")
    senza_agate.risposte[INCLUSO] = (201, {**APERTO[1], "gateway_url": "http://agate.agentlia.it"})
    with pytest.raises(fabbrica.ErroreFabbrica, match="indirizzo di Agate"):
        fabbrica.agate_incluso(superuser, None, "https://erp.esempio.it")
    senza_agate.risposte[INCLUSO] = (200, {**APERTO[1], "console_url": "javascript:x"})
    assert fabbrica.agate_incluso(superuser, None, "https://erp.esempio.it") == (CODICE, GATEWAY, "", "Adabox Srl")
    Azienda.objects.filter(pk=1).update(partita_iva="")
    superuser.email = ""
    with pytest.raises(fabbrica.ErroreFabbrica, match="serve la tua email"):
        fabbrica.agate_incluso(superuser, None, "https://erp.esempio.it")
    fabbrica.agate_incluso(superuser, None, "https://erp.esempio.it", email="mario@rossi.it")
    assert "vat" not in _inviate(senza_agate, INCLUSO)[-1]["corpo"]["company"]     # senza partita IVA: l'email


# ---------- «Da approvare» in frasi semplici ----------

@pytest.fixture
def opportunita(db):
    from crm.models import FaseCrm, Opportunita
    nuova = FaseCrm.objects.create(nome="Nuova", ordine=1)
    qualificata = FaseCrm.objects.create(nome="Qualificata", ordine=2)
    o = Opportunita.objects.create(azienda=Azienda.objects.get(pk=1), titolo="Preventivo gestionale per 3 negozi",
                                   fase=nuova)
    return o, qualificata


@pytest.fixture
def qualificatore(db):
    u = User.objects.create_user("awf-qualificatore", "", None)
    return Agente.objects.create(utente=u, nome="Qualificatore lead", agate_agent_id="agt_qual")


def _frase(**campi):
    a = Approvazione.objects.create(approval_id=f"apr_{Approvazione.objects.count() + 1}", **campi)
    return frasi.approvazione(a)


def test_frasi_dai_parametri(opportunita, qualificatore):
    o, qualificata = opportunita
    testo = _frase(strumento="awf.modifica_record", riepilogo="awf.modifica_record. Motivi: serve l'ok",
                   parametri={"vista": "crm.opportunita", "id": o.pk, "campi": {"fase": qualificata.pk}})
    assert testo == {"frase": "Il Qualificatore lead chiede di cambiare «Preventivo gestionale per 3 negozi»: "
                              "fase → Qualificata", "dettaglio": "Motivi: serve l'ok"}
    assert _frase(strumento="awf.modifica_record", parametri={"vista": "crm.opportunita", "id": o.pk,
                                                              "campi": {"priorita": 2, "chiusura_prevista":
                                                                        "2026-12-01"}})["frase"].endswith(
        "«Preventivo gestionale per 3 negozi»: priorità → Alta, chiusura prevista → 01/12/2026")
    assert _frase(strumento="awf.elimina_record", parametri={"vista": "crm.opportunita", "id": o.pk})["frase"] == \
        "Il Qualificatore lead chiede di eliminare «Preventivo gestionale per 3 negozi»"
    assert _frase(strumento="awf.pianifica_attivita",
                  parametri={"vista": "crm.opportunita", "id": o.pk, "tipo": "Chiamata", "scadenza": "2026-11-05"}
                  )["frase"] == ("Il Qualificatore lead chiede di lasciare un'attività su «Preventivo gestionale per 3 "
                                 "negozi»: Chiamata, entro il 05/11/2026")
    assert _frase(strumento="awf.esegui_bottone", parametri={"vista": "crm.opportunita", "id": o.pk,
                                                             "bottone": "segna_vinta"})["frase"].startswith(
        "Il Qualificatore lead chiede di premere «")
    assert _frase(strumento="awf.crea_record", parametri={"vista": "crm.opportunita",
                                                          "campi": {"titolo": "Nuovo lead"}})["frase"] == \
        "Il Qualificatore lead chiede di creare una voce in «Opportunità»: titolo → Nuovo lead"


def test_frasi_dal_riepilogo_e_chi_chiede(opportunita, qualificatore):
    riepilogo = "awf.modifica_record. Motivi: Le modifiche chiedono un ok; Sposto «Preventivo gestionale per 3 " \
                "negozi» in Qualificata"
    testo = _frase(strumento="awf.modifica_record", riepilogo=riepilogo)
    assert testo["frase"] == "Il Qualificatore lead chiede di cambiare «Preventivo gestionale per 3 negozi»"
    assert testo["dettaglio"].startswith("Motivi: Le modifiche") and "awf." not in str(testo)
    assert _frase(strumento="awf.esegui_bottone", riepilogo="awf.esegui_bottone")["frase"] == \
        "Il Qualificatore lead chiede di premere un bottone su un record"
    assert _frase(strumento="awf.lancia_razzi", riepilogo="Azione awf.lancia_razzi in attesa di approvazione") == \
        {"frase": "Il Qualificatore lead chiede il tuo ok per un'azione", "dettaglio": ""}
    altro = Agente.objects.create(utente=User.objects.create_user("awf-smistatore"), nome="Smistatore",
                                  agate_agent_id="agt_smi")
    assert _frase(strumento="awf.elimina_record", riepilogo="")["frase"] == "Un agente chiede di eliminare un record"
    assert _frase(strumento="awf.elimina_record", attore="agt_smi")["frase"].startswith("Lo Smistatore chiede")
    altro.nome = "Assistente vendite"
    altro.save()
    assert _frase(strumento="awf.elimina_record", attore="Assistente vendite")["frase"].startswith(
        "L'Assistente vendite chiede")


def test_da_approvare_mostra_la_frase(client, superuser, opportunita, qualificatore):
    from awf import webhook
    o, qualificata = opportunita
    webhook.gestisci("approval.requested", {
        "approval_id": "apr_q", "tool": "awf.modifica_record", "summary": "awf.modifica_record. Motivi: serve l'ok",
        "actor": {"id": "agt_qual"}, "params": {"vista": "crm.opportunita", "id": o.pk,
                                                 "campi": {"fase": qualificata.pk}}})
    a = Approvazione.objects.get(approval_id="apr_q")
    assert a.attore == "agt_qual" and a.parametri["id"] == o.pk
    webhook.gestisci("approval.requested", {"approval_id": "apr_s", "tool": "awf.modifica_record",
                                            "summary": "awf.modifica_record. Sposto «Offerta Rossi» in Vinta"})
    pagina = client.get("/agate/da-approvare/").content.decode()
    assert ("Il Qualificatore lead chiede di cambiare «Preventivo gestionale per 3 negozi»: fase → Qualificata"
            in pagina.replace("&#x27;", "'"))
    assert "Il Qualificatore lead chiede di cambiare «Offerta Rossi»" in pagina
    assert "«awf.modifica_record" not in pagina and "Un agente chiede il tuo ok" not in pagina


# ---------- contro gli abusi: la prova che adabox è davvero all'indirizzo dichiarato ----------

def test_la_fabbrica_legge_la_prova_durante_la_richiesta(client, senza_agate, agate, monkeypatch):
    senza_agate.risposte[INCLUSO] = APERTO
    lette = []

    def fabbrica_che_controlla(metodo, url, intestazioni, corpo, timeout):
        if url.endswith(INCLUSO):                       # come la fabbrica: GET {base_url}/awf/agate-incluso/prova/
            r = Client().get(PROVA)                     # senza sessione
            lette.append((r.status_code, r.json(), json.loads(corpo)["app"]["proof"], r["Cache-Control"]))
        return senza_agate(metodo, url, intestazioni, corpo, timeout)

    monkeypatch.setattr(fabbrica, "trasporto", fabbrica_che_controlla)
    assert client.post(URL, PASSWORD).status_code == 302
    [(stato, risposta, inviata, cache_control)] = lette
    assert stato == 200 and risposta == {"proof": inviata} and "no-cache" in cache_control
    assert Client().get(PROVA).status_code == 404 and not Collegamento.attuale().prova_incluso


def test_prova_solo_finche_in_attesa(db):
    assert Client().get(PROVA).status_code == 404                                    # nessuna prova
    prova = fabbrica.nuova_prova()
    assert Client().get(PROVA).json() == {"proof": prova}
    assert Client().post(PROVA).status_code == 405 and Client().head(PROVA).status_code == 405
    Collegamento.objects.update(prova_scade=timezone.now() - datetime.timedelta(seconds=1))
    assert Client().get(PROVA).status_code == 404                                    # scaduta (10 minuti)
    fabbrica.nuova_prova()
    Collegamento.objects.update(prova_incluso="non-una-prova")
    assert Client().get(PROVA).status_code == 404


def test_prova_dimenticata_anche_se_la_fabbrica_non_risponde(client, senza_agate, agate):
    senza_agate.risposte[INCLUSO] = (fabbrica.ErroreFabbrica("fabbrica non raggiungibile (URLError)"), {})
    client.post(URL, PASSWORD)
    assert Client().get(PROVA).status_code == 404 and not Collegamento.attuale().prova_incluso


def test_gestionale_non_raggiungibile(client, senza_agate, agate):
    senza_agate.risposte[INCLUSO] = (422, {"title": "Dati non validi",
                                           "detail": "il gestionale non risponde all'indirizzo indicato"})
    pagina = html.unescape(client.post(URL, PASSWORD).content.decode())
    assert ("Agentlia non raggiunge adabox all'indirizzo https://erp.esempio.it: l'indirizzo pubblico di adabox deve "
            "rispondere da internet in https. Non è stata inviata nessuna richiesta") in pagina
    assert 'href="/awf/avanzate/">Agenti AI → Avanzate</a>: deve essere in https e aperto verso internet' in pagina
    assert '>Riprova</button>' in pagina and not RichiestaAgenti.objects.exists()
    assert not CollegamentoAgate.objects.exists() and not agate.chiamate


def test_limite_di_oggi_detto_chiaro_e_torna_al_codice(client, senza_agate, agate):
    senza_agate.risposte[INCLUSO] = (503, {"title": "Servizio non disponibile",
                                           "detail": "Agate incluso ha raggiunto il limite di oggi, riprova domani."})
    r = client.post(URL, PASSWORD)
    assert r.status_code == 302 and not CollegamentoAgate.objects.exists() and not agate.chiamate
    senza_agate.risposte[STATO] = _stato("received")
    pagina = html.unescape(client.get(r["Location"]).content.decode())
    assert ("Agate incluso ha raggiunto il limite di oggi, riprova domani: per questa volta il Controllo AI (Agate) "
            "non si attiva da solo. La richiesta è partita; per farla proseguire collega il Controllo AI con un codice "
            "di Agate.") in pagina
    assert "Collega il Controllo AI" in pagina                                      # il percorso con il codice
    assert "Prima serve un passaggio da fare una volta sola" in client.get(URL).content.decode()
