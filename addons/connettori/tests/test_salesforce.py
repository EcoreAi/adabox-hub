"""Salesforce: il formato delle chiamate, l'accesso «client credentials» e la sincronia nei due versi contro
l'organizzazione finta, con lo stesso motore di HubSpot."""
import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs

import httpx2 as httpx
import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone

import crm
from connettori import riferimenti, sincronia, sistemi
from connettori.forms import CollegamentoForm
from connettori.models import CollegamentoEsterno, RecordProva
from connettori.sistemi import prova_salesforce as finto
from connettori.sistemi import salesforce
from connettori.sistemi.base import AZIENDE, OPPORTUNITA, PERSONE, Deposito, ErroreConnettore, ErroreTemporaneo
from contatti.models import Contatto
from core import cifratura
from core.models import Azienda, Sequenza
from crm.models import FaseCrm, Opportunita

pytestmark = pytest.mark.django_db
SF = CollegamentoEsterno.SALESFORCE


@pytest.fixture
def azienda():
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    a = Azienda.objects.first()
    Sequenza.objects.get_or_create(codice="contatti.contatto", azienda=a, defaults={"formato": "C{numero:05d}"})
    return a


@pytest.fixture
def esterno(azienda):
    return CollegamentoEsterno.objects.create(azienda=azienda, sistema=SF, comanda=CollegamentoEsterno.ESTERNO)


@pytest.fixture
def adabox(azienda):
    return CollegamentoEsterno.objects.create(azienda=azienda, sistema=SF, comanda=CollegamentoEsterno.ADABOX)


def _cliente(c, fase="Proposal/Price Quote"):
    """Su Salesforce: un'azienda, una persona che ci lavora e un'opportunità con la persona nei ruoli."""
    az = finto.scrivi(c, {"Name": "Verdi Srl", "Website": "https://www.verdi.it", "BillingCity": "Bergamo", "BillingCountry": "IT"},
                      finto.nuovo_id(AZIENDE), AZIENDE)
    persona = finto.scrivi(c, {"FirstName": "Anna", "LastName": "Bassi", "Email": "Anna@Verdi.it", "Title": "Acquisti", "AccountId": az.id_esterno},
                           finto.nuovo_id(PERSONE))
    tr = finto.scrivi(c, {"Name": "Impianto nuovo", "Amount": 12500.5, "CloseDate": "2026-12-15", "StageName": fase, "AccountId": az.id_esterno},
                      finto.nuovo_id(OPPORTUNITA), OPPORTUNITA)
    finto.associa(c, tr, persona)
    return persona, az, tr


# --- il client: formato delle chiamate e accesso ------------------------------------------------------------------

def _sf(gestore, deposito=None):
    return salesforce.Salesforce("acme.my.salesforce.com", "cid", "segreto", deposito=deposito, transport=httpx.MockTransport(gestore))


def _token_e(gestore_api):
    viste = []

    def gestore(r):
        viste.append(r)
        if r.url.path == "/services/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok", "instance_url": "https://acme.my.salesforce.com"})
        return gestore_api(r)
    return gestore, viste


def test_accesso_client_credentials_sul_my_domain_e_soql_senza_virgolette():
    gestore, viste = _token_e(lambda r: httpx.Response(200, json={"done": False, "records": [{"Id": "003A", "SystemModstamp": "x"}],
                                                                   "nextRecordsUrl": "/services/data/v66.0/query/01g-200"}))
    record, dopo = _sf(gestore).modificati(PERSONE, datetime.datetime(2026, 11, 1, 8, 30, tzinfo=datetime.timezone.utc))
    token, query = viste
    assert str(token.url) == "https://acme.my.salesforce.com/services/oauth2/token" and token.method == "POST"
    assert parse_qs(token.content.decode()) == {"grant_type": ["client_credentials"], "client_id": ["cid"], "client_secret": ["segreto"]}
    soql = query.url.params["q"]
    assert query.url.path == f"/services/data/{salesforce.VERSIONE}/query" and query.headers["Authorization"] == "Bearer tok"
    assert "FROM Contact WHERE SystemModstamp >= 2026-11-01T08:30:00Z ORDER BY SystemModstamp ASC" in soql and "AccountId" in soql
    assert query.headers["Sforce-Query-Options"] == "batchSize=200"
    assert record == [{"Id": "003A", "SystemModstamp": "x", "id": "003A"}] and dopo == "/services/data/v66.0/query/01g-200"


def test_la_pagina_dopo_si_segue_solo_dentro_le_api():
    gestore, viste = _token_e(lambda r: httpx.Response(200, json={"done": True, "records": []}))
    _sf(gestore).modificati(PERSONE, timezone.now(), "/services/data/v66.0/query/01g-200")
    assert viste[-1].url.path == "/services/data/v66.0/query/01g-200"
    with pytest.raises(ErroreConnettore):
        _sf(gestore).modificati(PERSONE, timezone.now(), "https://altrove.example/rubare")


@pytest.mark.parametrize("dominio", ["acme.salesforce.com", "evil.example", "my.salesforce.com.evil.example", "", "https://x.my.salesforce.com.evil.it"])
def test_il_segreto_va_solo_a_un_my_domain(dominio):
    with pytest.raises(ErroreConnettore, match="My Domain"):
        salesforce.Salesforce(dominio, "cid", "s")


def test_dominio_accettato_anche_con_https_e_sandbox():
    assert salesforce.dominio_valido("https://Acme.my.salesforce.com/") == "acme.my.salesforce.com"
    assert salesforce.dominio_valido("acme--dev.sandbox.my.salesforce.com") == "acme--dev.sandbox.my.salesforce.com"


def test_istanza_fuori_da_salesforce_si_rifiuta():
    sf = _sf(lambda r: httpx.Response(200, json={"access_token": "tok", "instance_url": "https://evil.example"}))
    with pytest.raises(ErroreConnettore, match="inatteso"):
        sf.verifica()


def test_credenziali_sbagliate_si_dicono_senza_il_segreto():
    sf = _sf(lambda r: httpx.Response(400, json={"error": "invalid_client", "error_description": "invalid client credentials"}))
    with pytest.raises(ErroreConnettore) as e:
        sf.verifica()
    assert "Connected App" in str(e.value) and "segreto" not in str(e.value).split("(")[-1]


def test_token_scaduto_se_ne_chiede_uno_nuovo_una_volta():
    chiesti = []

    def gestore(r):
        if r.url.path == "/services/oauth2/token":
            chiesti.append(1)
            return httpx.Response(200, json={"access_token": f"tok{len(chiesti)}", "instance_url": "https://acme.my.salesforce.com"})
        if r.headers["Authorization"] == "Bearer tok1":
            return httpx.Response(401, json=[{"message": "Session expired or invalid", "errorCode": "INVALID_SESSION_ID"}])
        return httpx.Response(200, json={"done": True, "records": []})
    _sf(gestore).verifica()
    assert len(chiesti) == 2


@pytest.mark.parametrize("stato,corpo,errore", [
    (403, [{"message": "TotalRequests Limit exceeded.", "errorCode": "REQUEST_LIMIT_EXCEEDED"}], ErroreTemporaneo),
    (503, [], ErroreTemporaneo),
    (400, [{"message": "Required fields are missing: [LastName]", "errorCode": "REQUIRED_FIELD_MISSING"}], ErroreConnettore),
])
def test_errori_temporanei_e_definitivi(stato, corpo, errore):
    gestore, _ = _token_e(lambda r: httpx.Response(stato, json=corpo))
    with pytest.raises(errore) as e:
        _sf(gestore).crea(PERSONE, {"LastName": "x"})
    if stato == 400:
        assert not isinstance(e.value, ErroreTemporaneo) and "LastName" in str(e.value)


def test_il_token_si_riusa_tra_un_client_e_l_altro():
    class Memoria(Deposito):
        valore = None

        def leggi(self):
            return self.valore

        def salva(self, token, scade):
            Memoria.valore = token
    gestore, viste = _token_e(lambda r: httpx.Response(200, json={"done": True, "records": []}))
    _sf(gestore, Memoria()).verifica()
    _sf(gestore, Memoria()).verifica()
    chiesti = [v for v in viste if v.url.path == "/services/oauth2/token"]
    assert len(chiesti) == 1


def test_valori_tra_apici_escapati():
    gestore, viste = _token_e(lambda r: httpx.Response(200, json={"done": True, "records": []}))
    assert _sf(gestore).trova(PERSONE, "email", "o'neil\\@x.it") is None
    assert viste[-1].url.params["q"] == "SELECT Id FROM Contact WHERE Email = 'o\\'neil\\\\@x.it' LIMIT 2"


# --- con l'organizzazione finta: dall'esterno ad adabox -----------------------------------------------------------

def test_import_aziende_persone_opportunita_con_ruoli(esterno, azienda):
    _, az, tr = _cliente(esterno)
    testo = sincronia.giro(esterno.pk)
    assert "Creati 1" in testo and "aziende: create 1" in testo and "opportunità: create 1" in testo, testo
    ditta = riferimenti.trova(Contatto, azienda, SF, sincronia.chiave_azienda(az.id_esterno))
    assert ditta.tipo == Contatto.AZIENDA and ditta.nome == "Verdi Srl" and ditta.citta == "Bergamo" and ditta.nazione == "IT"
    persona = Contatto.objects.get(tipo=Contatto.PERSONA)
    assert persona.societa == ditta and persona.email == "anna@verdi.it" and persona.ruolo == "Acquisti"
    o = riferimenti.trova(Opportunita, azienda, SF, tr.id_esterno)
    assert o.titolo == "Impianto nuovo" and o.valore_atteso == Decimal("12500.50") and o.contatto == ditta
    assert o.chiusura_prevista.isoformat() == "2026-12-15" and o.fase.nome == "Negoziazione" and o.stato == Opportunita.APERTA     # 75%: la più vicina è 80%
    esterno.refresh_from_db()
    assert not esterno.in_errore and esterno.accesso_cifrato and "prova-sf" not in esterno.accesso_cifrato        # token cifrato


def test_vinta_e_persa_da_iswon(esterno, azienda):
    _, _, tr = _cliente(esterno, fase="Closed Won")
    sincronia.giro(esterno.pk)
    o = Opportunita.objects.get()
    assert o.stato == Opportunita.VINTA and o.fase.vinta
    finto.scrivi(esterno, {"StageName": "Closed Lost"}, tr.id_esterno, OPPORTUNITA)
    sincronia.giro(esterno.pk)
    o.refresh_from_db()
    assert o.stato == Opportunita.PERSA


def test_rileggere_non_duplica_e_le_pagine_si_seguono(esterno, azienda, monkeypatch):
    monkeypatch.setattr(salesforce, "PER_PAGINA", 2)
    for i in range(5):
        finto.scrivi(esterno, {"LastName": f"N{i}", "Email": f"n{i}@x.it"}, finto.nuovo_id(PERSONE))
    assert "Creati 5" in sincronia.giro(esterno.pk)
    assert "Creati 0, aggiornati 0, uguali" in sincronia.giro(esterno.pk) and Contatto.objects.count() == 5


# --- da adabox a Salesforce ------------------------------------------------------------------------------------------

def _salva(capture, modello, **campi):
    with capture(execute=True):
        return modello.objects.create(**campi)


def test_azienda_persona_e_opportunita_partono_con_i_campi_obbligatori(adabox, azienda, django_capture_on_commit_callbacks):
    ditta = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Rossi Srl", tipo=Contatto.AZIENDA, sito="https://www.rossi.it")
    persona = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Mario", email="m@rossi.it", tipo=Contatto.PERSONA,
                     societa=ditta)
    o = _salva(django_capture_on_commit_callbacks, Opportunita, azienda=azienda, titolo="Rinnovo", contatto=persona,
               valore_atteso=Decimal("3000"), fase=FaseCrm.objects.get(nome="Negoziazione"))
    r_az, r_p, r_o = (RecordProva.objects.get(tipo=t) for t in (AZIENDE, PERSONE, OPPORTUNITA))
    assert r_az.proprieta["Name"] == "Rossi Srl" and r_az.id_esterno.startswith("001")
    assert r_p.proprieta["LastName"] == "Mario" and "FirstName" not in r_p.proprieta and r_p.proprieta["AccountId"] == r_az.id_esterno
    assert r_o.proprieta["StageName"] == "Proposal/Price Quote" and r_o.proprieta["Amount"] == 3000.0 and r_o.proprieta["AccountId"] == r_az.id_esterno
    assert r_o.proprieta["CloseDate"] == (timezone.localdate() + datetime.timedelta(days=salesforce.GIORNI_CHIUSURA)).isoformat()
    assert r_o.associazioni[PERSONE] == [r_p.id_esterno]                       # OpportunityContactRole
    assert riferimenti.id_esterno(o, SF) == r_o.id_esterno and riferimenti.id_esterno(persona, SF) == r_p.id_esterno
    with django_capture_on_commit_callbacks(execute=True):
        o.fase = FaseCrm.objects.get(vinta=True)
        o.save()
    r_o.refresh_from_db()
    assert r_o.proprieta["StageName"] == "Closed Won" and r_o.associazioni[PERSONE] == [r_p.id_esterno]    # il ruolo non si duplica


def test_azienda_gia_presente_per_dominio(adabox, azienda, django_capture_on_commit_callbacks):
    r = finto.scrivi(adabox, {"Name": "Rossi S.r.l.", "Website": "https://www.rossi.it/chi-siamo"}, finto.nuovo_id(AZIENDE), AZIENDE)
    finto.scrivi(adabox, {"Name": "Grossi", "Website": "https://grossi.it"}, finto.nuovo_id(AZIENDE), AZIENDE)    # contiene «rossi.it»
    ditta = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Rossi Srl", tipo=Contatto.AZIENDA, sito="rossi.it")
    assert RecordProva.objects.filter(tipo=AZIENDE).count() == 2
    assert riferimenti.id_esterno(ditta, SF) == sincronia.chiave_azienda(r.id_esterno)


def test_persona_gia_presente_per_email(adabox, azienda, django_capture_on_commit_callbacks):
    r = finto.scrivi(adabox, {"LastName": "Rossi", "Email": "m@rossi.it"}, finto.nuovo_id(PERSONE))
    c = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Mario Rossi", email="m@rossi.it", tipo=Contatto.PERSONA)
    assert RecordProva.objects.count() == 1 and riferimenti.id_esterno(c, SF) == r.id_esterno
    r.refresh_from_db()
    assert r.proprieta["FirstName"] == "Mario"


# --- il collegamento: modulo e pagina --------------------------------------------------------------------------------

def test_collegamento_vero_chiede_my_domain_client_id_e_segreto():
    vuoto = CollegamentoForm(data={"sistema": SF, "modalita": "vera", "comanda": "esterno", "attivo": "on"})
    assert {"indirizzo", "client_id", "nuovo_segreto"} <= set(vuoto.errors)
    sbagliato = CollegamentoForm(data={"sistema": SF, "modalita": "vera", "comanda": "esterno", "attivo": "on", "indirizzo": "evil.example",
                                       "client_id": "c", "nuovo_segreto": "s"})
    assert "My Domain" in str(sbagliato.errors["indirizzo"])
    giusto = CollegamentoForm(data={"sistema": SF, "modalita": "vera", "comanda": "esterno", "attivo": "on",
                                    "indirizzo": "https://acme.my.salesforce.com", "client_id": "c", "nuovo_segreto": "s"})
    assert giusto.is_valid() and giusto.cleaned_data["indirizzo"] == "acme.my.salesforce.com"


def test_il_client_vero_usa_le_credenziali_cifrate(azienda):
    c = CollegamentoEsterno.objects.create(azienda=azienda, sistema=SF, modalita=CollegamentoEsterno.VERA)
    with pytest.raises(ErroreConnettore, match="My Domain"):
        sistemi.client(c)
    c.indirizzo, c.client_id, c.segreto_cifrato = "acme.my.salesforce.com", "cid", cifratura.cifra("sss")
    s = sistemi.client(c)
    assert isinstance(s, salesforce.Salesforce) and s.segreto == "sss" and s.host == "acme.my.salesforce.com"


def test_dalla_pagina_si_prova_tutto(client, esterno, azienda):
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([azienda])
    root.profilo.azienda_predefinita = azienda
    root.profilo.save()
    client.force_login(root)
    base = f"/connettori/collegamenti/{esterno.pk}/"
    assert client.post(base + "bottone/simula_nuovo/").status_code == 302 and RecordProva.objects.count() == 3
    assert client.post(base + "bottone/verifica/").status_code == 302
    assert client.post(base + "bottone/sincronizza/").status_code == 302
    assert Opportunita.objects.count() == 1 and Contatto.objects.get(tipo=Contatto.PERSONA).societa is not None
    pagina = client.get(base).content.decode()
    assert "Collegati: 1 persone, 1 aziende, 1 opportunità" in pagina and "Salesforce" in pagina
    assert client.post(base + "bottone/simula_modifica/").status_code == 302

