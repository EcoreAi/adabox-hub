"""Zoho CRM: refresh token e api_domain, letture con If-Modified-Since, ricerca che «contiene», fasi senza
probabilità, e la sincronia nei due versi contro l'account finto, con lo stesso motore di HubSpot."""
import datetime
from decimal import Decimal
from pathlib import Path

import httpx2 as httpx
import pytest
from django.core.management import call_command

import crm
from connettori import riferimenti, sincronia
from connettori.forms import CollegamentoForm
from connettori.models import CollegamentoEsterno, RecordProva
from connettori.sistemi import prova_zoho as finto
from connettori.sistemi import zoho
from connettori.sistemi.base import AZIENDE, OPPORTUNITA, PERSONE, ErroreConnettore, ErroreTemporaneo
from contatti.models import Contatto
from core.models import Azienda, Sequenza
from crm.models import FaseCrm, Opportunita

pytestmark = pytest.mark.django_db
ZO = CollegamentoEsterno.ZOHO


@pytest.fixture
def azienda():
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    a = Azienda.objects.first()
    Sequenza.objects.get_or_create(codice="contatti.contatto", azienda=a, defaults={"formato": "C{numero:05d}"})
    return a


@pytest.fixture
def esterno(azienda):
    return CollegamentoEsterno.objects.create(azienda=azienda, sistema=ZO, comanda=CollegamentoEsterno.ESTERNO)


@pytest.fixture
def adabox(azienda):
    return CollegamentoEsterno.objects.create(azienda=azienda, sistema=ZO, comanda=CollegamentoEsterno.ADABOX)


def _cliente(c, fase="Proposal/Price Quote"):
    az = finto.scrivi(c, {"Account_Name": "Verdi Srl", "Website": "www.verdi.it", "Billing_City": "Bergamo"}, finto.nuovo_id(), AZIENDE)
    lookup = {"Account_Name": {"id": az.id_esterno, "name": "Verdi Srl"}}
    persona = finto.scrivi(c, {"First_Name": "Anna", "Last_Name": "Bassi", "Email": "anna@verdi.it", "Mobile": "333", **lookup}, finto.nuovo_id())
    tr = finto.scrivi(c, {"Deal_Name": "Impianto nuovo", "Amount": 12500.5, "Closing_Date": "2026-12-15", "Stage": fase, **lookup,
                          "Contact_Name": {"id": persona.id_esterno, "name": "Anna Bassi"}}, finto.nuovo_id(), OPPORTUNITA)
    return persona, az, tr


# --- il client --------------------------------------------------------------------------------------------------------

def _zo(gestore):
    return zoho.Zoho("eu", "cid", "segreto", "rt", transport=httpx.MockTransport(gestore))


def _token_e(gestore_api, api="https://www.zohoapis.eu"):
    viste = []

    def gestore(r):
        viste.append(r)
        if r.url.path == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": "tok", "api_domain": api, "token_type": "Bearer", "expires_in": 3600})
        return gestore_api(r)
    return gestore, viste


def test_refresh_token_nel_data_center_e_letture_con_if_modified_since():
    gestore, viste = _token_e(lambda r: httpx.Response(200, json={"data": [{"id": 7, "Modified_Time": "2026-11-01T09:30:00+01:00"}],
                                                                   "info": {"more_records": True, "page": 1}}))
    record, dopo = _zo(gestore).modificati(PERSONE, datetime.datetime(2026, 11, 1, 8, 30, 5, 123, tzinfo=datetime.timezone.utc))
    token, lettura = viste
    assert token.url.host == "accounts.zoho.eu" and token.method == "POST"
    assert dict(token.url.params) == {"refresh_token": "rt", "client_id": "cid", "client_secret": "segreto", "grant_type": "refresh_token"}
    assert str(lettura.url).startswith("https://www.zohoapis.eu/crm/v8/Contacts?") and lettura.headers["Authorization"] == "Zoho-oauthtoken tok"
    assert lettura.headers["If-Modified-Since"] == "2026-11-01T08:30:05+00:00"
    p = lettura.url.params
    assert p["sort_by"] == "Modified_Time" and p["sort_order"] == "asc" and "Account_Name" in p["fields"] and p["page"] == "1"
    assert record == [{"id": "7", "Modified_Time": "2026-11-01T09:30:00+01:00"}] and dopo == "p:2"


def test_oltre_le_2000_si_passa_al_page_token():
    gestore, viste = _token_e(lambda r: httpx.Response(200, json={"data": [], "info": {"more_records": True, "next_page_token": "abc"}}))
    _, dopo = _zo(gestore).modificati(PERSONE, datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc), "p:10")
    assert dopo == "t:abc"
    _zo(gestore).modificati(PERSONE, datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc), "t:abc")
    assert viste[-1].url.params["page_token"] == "abc" and "page" not in viste[-1].url.params


def test_nessun_record_e_204_o_304():
    for stato in (204, 304):
        gestore, _ = _token_e(lambda r, s=stato: httpx.Response(s))
        assert _zo(gestore).modificati(AZIENDE, datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)) == ([], None)


def test_api_domain_fuori_da_zoho_si_rifiuta():
    gestore, _ = _token_e(lambda r: httpx.Response(200, json={}), api="https://evil.example")
    with pytest.raises(ErroreConnettore, match="inatteso"):
        _zo(gestore).verifica()


def test_data_center_sconosciuto_si_rifiuta():
    with pytest.raises(ErroreConnettore, match="data center"):
        zoho.Zoho("evil.example", "c", "s", "r")


def test_token_scaduto_se_ne_chiede_uno_nuovo_una_volta():
    chiesti = []

    def gestore(r):
        if r.url.path == "/oauth/v2/token":
            chiesti.append(1)
            return httpx.Response(200, json={"access_token": f"tok{len(chiesti)}", "api_domain": "https://www.zohoapis.eu", "expires_in": 3600})
        if r.headers["Authorization"] == "Zoho-oauthtoken tok1":
            return httpx.Response(401, json={"code": "INVALID_TOKEN", "details": {}, "message": "invalid oauth token", "status": "error"})
        return httpx.Response(204)
    _zo(gestore).verifica()
    assert len(chiesti) == 2


@pytest.mark.parametrize("stato,corpo,errore", [
    (429, {}, ErroreTemporaneo),
    (500, {}, ErroreTemporaneo),
    (401, {"code": "OAUTH_SCOPE_MISMATCH", "message": "invalid oauth scope"}, ErroreConnettore),
])
def test_errori_temporanei_e_definitivi(stato, corpo, errore):
    gestore, _ = _token_e(lambda r: httpx.Response(stato, json=corpo))
    with pytest.raises(errore) as e:
        _zo(gestore).verifica()
    if stato == 401:
        assert "ambiti" in str(e.value) and not isinstance(e.value, ErroreTemporaneo)


def test_refresh_token_rifiutato_si_dice():
    sf = _zo(lambda r: httpx.Response(200, json={"error": "invalid_code"}))
    with pytest.raises(ErroreConnettore, match="refresh token") as e:
        sf.verifica()
    assert not isinstance(e.value, ErroreTemporaneo)


def test_la_ricerca_che_contiene_si_filtra_qui():
    risposta = {"data": [{"id": 1, "Email": "anna@verdi.it.old"}, {"id": 2, "Email": "Anna@Verdi.it"}]}
    gestore, viste = _token_e(lambda r: httpx.Response(200, json=risposta))
    assert _zo(gestore).trova(PERSONE, "email", "anna@verdi.it") == "2"
    assert viste[-1].url.params["criteria"] == "(Email:equals:anna@verdi.it)"
    gestore, viste = _token_e(lambda r: httpx.Response(204))
    assert _zo(gestore).trova(AZIENDE, "nome", "Rossi (Milano), Srl") is None
    assert viste[-1].url.params["criteria"] == "(Account_Name:equals:Rossi \\(Milano\\)\\, Srl)"


def test_rifiuto_e_doppione():
    gestore, _ = _token_e(lambda r: httpx.Response(400, json={"data": [{"code": "MANDATORY_NOT_FOUND", "details": {"api_name": "Last_Name"},
                                                                         "message": "required field not found", "status": "error"}]}))
    with pytest.raises(ErroreConnettore, match="Last_Name"):
        _zo(gestore).crea(PERSONE, {"Email": "x@y.it"})
    gestore, _ = _token_e(lambda r: httpx.Response(400, json={"data": [{"code": "DUPLICATE_DATA", "details": {"api_name": "Email", "id": "99"},
                                                                         "message": "duplicate data", "status": "error"}]}))
    assert _zo(gestore).crea(PERSONE, {"Last_Name": "x", "Email": "x@y.it"}) == "99"


def test_fasi_senza_probabilita():
    fasi = zoho.Zoho(finto.CENTRO, "c", "s", "r", transport=finto.trasporto(None)).fasi()
    per_nome = {f["id"]: f for f in fasi}
    assert "-None-" not in per_nome and per_nome["Closed Won"]["vinta"] and per_nome["Closed Won"]["chiusa"]
    assert per_nome["Closed Lost"]["chiusa"] and not per_nome["Closed Lost"]["vinta"] and not per_nome["Closed-Lost to Competition"]["vinta"]
    aperte = [f["probabilita"] for f in fasi if not f["chiusa"]]
    assert len(aperte) == 6 and aperte == sorted(aperte) and 0 < aperte[0] < aperte[-1] < 1


def test_fasi_con_tipo_e_probabilita_se_zoho_li_manda():
    campi = {"fields": [{"api_name": "Stage", "pick_list_values": [
        {"actual_value": "Firmato", "display_value": "Firmato", "sequence_number": 2, "probability": 100, "forecast_type": "Closed Won"},
        {"actual_value": "In corso", "display_value": "In corso", "sequence_number": 1, "probability": 40, "forecast_type": "Open"}]}]}
    gestore, _ = _token_e(lambda r: httpx.Response(200, json=campi))
    assert [(f["id"], f["probabilita"], f["chiusa"], f["vinta"]) for f in _zo(gestore).fasi()] == [("In corso", 0.4, False, False),
                                                                                                    ("Firmato", 1.0, True, True)]


# --- con l'account finto: dall'esterno ad adabox -----------------------------------------------------------------

def test_import_aziende_persone_opportunita_con_lookup(esterno, azienda):
    _, az, tr = _cliente(esterno)
    testo = sincronia.giro(esterno.pk)
    assert "Creati 1" in testo and "aziende: create 1" in testo and "opportunità: create 1" in testo, testo
    ditta = riferimenti.trova(Contatto, azienda, ZO, sincronia.chiave_azienda(az.id_esterno))
    assert ditta.nome == "Verdi Srl" and ditta.citta == "Bergamo" and ditta.sito == "www.verdi.it"
    persona = Contatto.objects.get(tipo=Contatto.PERSONA)
    assert persona.societa == ditta and persona.cellulare == "333"
    o = riferimenti.trova(Opportunita, azienda, ZO, tr.id_esterno)
    assert o.titolo == "Impianto nuovo" and o.valore_atteso == Decimal("12500.50") and o.contatto == ditta and o.stato == Opportunita.APERTA
    assert o.chiusura_prevista.isoformat() == "2026-12-15"


def test_vinta_e_persa(esterno, azienda):
    _, _, tr = _cliente(esterno, fase="Closed Won")
    sincronia.giro(esterno.pk)
    o = Opportunita.objects.get()
    assert o.stato == Opportunita.VINTA and o.fase.vinta
    finto.scrivi(esterno, {"Stage": "Closed-Lost to Competition"}, tr.id_esterno, OPPORTUNITA)
    sincronia.giro(esterno.pk)
    o.refresh_from_db()
    assert o.stato == Opportunita.PERSA


def test_rileggere_non_duplica_e_le_pagine_si_seguono(esterno, azienda, monkeypatch):
    monkeypatch.setattr(zoho, "PER_PAGINA", 2)
    for i in range(5):
        finto.scrivi(esterno, {"Last_Name": f"N{i}", "Email": f"n{i}@x.it"}, finto.nuovo_id())
    assert "Creati 5" in sincronia.giro(esterno.pk)
    assert "Creati 0, aggiornati 0" in sincronia.giro(esterno.pk) and Contatto.objects.count() == 5


# --- da adabox a Zoho -------------------------------------------------------------------------------------------------

def _salva(capture, modello, **campi):
    with capture(execute=True):
        return modello.objects.create(**campi)


def test_azienda_persona_e_opportunita_partono_con_i_lookup(adabox, azienda, django_capture_on_commit_callbacks):
    ditta = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Rossi Srl", tipo=Contatto.AZIENDA, sito="https://rossi.it")
    persona = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Mario Rossi", email="m@rossi.it", tipo=Contatto.PERSONA,
                     societa=ditta)
    o = _salva(django_capture_on_commit_callbacks, Opportunita, azienda=azienda, titolo="Rinnovo", contatto=persona,
               valore_atteso=Decimal("3000"), fase=FaseCrm.objects.get(nome="Nuova"))
    r_az, r_p, r_o = (RecordProva.objects.get(tipo=t) for t in (AZIENDE, PERSONE, OPPORTUNITA))
    assert r_az.proprieta["Account_Name"] == "Rossi Srl"
    assert r_p.proprieta["First_Name"] == "Mario" and r_p.proprieta["Last_Name"] == "Rossi"
    assert r_p.proprieta["Account_Name"] == {"id": r_az.id_esterno, "name": "Rossi Srl"}
    assert r_o.proprieta["Deal_Name"] == "Rinnovo" and r_o.proprieta["Amount"] == 3000.0 and r_o.proprieta["Stage"] == "Qualification"
    assert r_o.proprieta["Contact_Name"]["id"] == r_p.id_esterno and r_o.proprieta["Account_Name"]["id"] == r_az.id_esterno
    assert riferimenti.id_esterno(o, ZO) == r_o.id_esterno
    adabox.refresh_from_db()
    assert not adabox.in_errore, adabox.ultimo_esito


def test_azienda_trovata_per_dominio_non_per_somiglianza(adabox, azienda, django_capture_on_commit_callbacks):
    finto.scrivi(adabox, {"Account_Name": "Grossi", "Website": "https://grossi.it"}, finto.nuovo_id(), AZIENDE)
    r = finto.scrivi(adabox, {"Account_Name": "Rossi S.r.l.", "Website": "https://www.rossi.it"}, finto.nuovo_id(), AZIENDE)
    ditta = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Rossi Srl", tipo=Contatto.AZIENDA, sito="rossi.it")
    assert RecordProva.objects.filter(tipo=AZIENDE).count() == 2
    assert riferimenti.id_esterno(ditta, ZO) == sincronia.chiave_azienda(r.id_esterno)


# --- il collegamento --------------------------------------------------------------------------------------------------

def test_collegamento_vero_chiede_data_center_e_credenziali():
    vuoto = CollegamentoForm(data={"sistema": ZO, "modalita": "vera", "comanda": "esterno", "attivo": "on"})
    assert {"indirizzo", "client_id", "nuovo_segreto", "nuovo_token"} <= set(vuoto.errors)
    giusto = CollegamentoForm(data={"sistema": ZO, "modalita": "vera", "comanda": "esterno", "attivo": "on", "indirizzo": "EU",
                                    "client_id": "c", "nuovo_segreto": "s", "nuovo_token": "r"})
    assert giusto.is_valid() and giusto.cleaned_data["indirizzo"] == "eu"


def test_cambiare_sistema_azzera_cursori_token_e_segreti(esterno):
    sincronia.giro(esterno.pk)
    esterno.refresh_from_db()
    esterno.cursori = {"companies": "2026-01-01T00:00:00+00:00"}
    esterno.save()
    form = CollegamentoForm(instance=esterno, data={"sistema": "salesforce", "modalita": "prova", "comanda": "esterno", "attivo": "on"})
    assert form.is_valid(), form.errors
    c = form.save()
    assert c.cursori == {} and c.cursore is None and not c.accesso_cifrato and not c.token_cifrato
