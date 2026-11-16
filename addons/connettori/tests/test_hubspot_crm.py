"""HubSpot oltre le persone: aziende, opportunità, fasi della pipeline e associazioni, nei due versi."""
import datetime
import json
from decimal import Decimal
from pathlib import Path

import httpx2 as httpx
import pytest
from django.core.management import call_command

import crm
from connettori import riferimenti, sincronia
from connettori.models import CollegamentoEsterno, RecordProva
from connettori.sistemi import hubspot, prova
from connettori.sistemi.hubspot import AZIENDE, CONTATTI, OPPORTUNITA
from contatti.models import Contatto
from core.models import Azienda, Sequenza
from crm.models import FaseCrm, Opportunita

pytestmark = pytest.mark.django_db


@pytest.fixture
def azienda():
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    a = Azienda.objects.first()
    Sequenza.objects.get_or_create(codice="contatti.contatto", azienda=a, defaults={"formato": "C{numero:05d}"})
    return a


@pytest.fixture
def esterno(azienda):
    return CollegamentoEsterno.objects.create(azienda=azienda, comanda=CollegamentoEsterno.ESTERNO)


@pytest.fixture
def adabox(azienda):
    return CollegamentoEsterno.objects.create(azienda=azienda, comanda=CollegamentoEsterno.ADABOX)


def _cliente(c, ditta="Verdi Srl", fase="presentationscheduled"):
    persona = prova.scrivi(c, {"firstname": "Anna", "lastname": "Bassi", "email": "anna@verdi.it"})
    azienda = prova.scrivi(c, {"name": ditta, "domain": "verdi.it", "city": "Bergamo", "phone": "035 1"}, tipo=AZIENDE)
    prova.associa(c, persona, azienda)
    trattativa = prova.scrivi(c, {"dealname": "Impianto nuovo", "amount": "12500.50", "closedate": "2026-12-15T00:00:00Z",
                                  "pipeline": "default", "dealstage": fase}, tipo=OPPORTUNITA)
    prova.associa(c, trattativa, azienda)
    prova.associa(c, trattativa, persona)
    return persona, azienda, trattativa


# --- il client: formato delle chiamate ----------------------------------------------------------------------------

def _hs(gestore):
    return hubspot.HubSpot("t", transport=httpx.MockTransport(gestore))


def test_ricerca_aziende_usa_hs_lastmodifieddate():
    viste = []
    _hs(lambda r: viste.append(r) or httpx.Response(200, json={"results": []})).modificati(AZIENDE, datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
    corpo = json.loads(viste[0].content)
    assert viste[0].url.path == "/crm/v3/objects/companies/search"
    assert corpo["filterGroups"][0]["filters"][0]["propertyName"] == "hs_lastmodifieddate" and "name" in corpo["properties"]


def test_associazioni_e_fasi_nel_formato_v4():
    viste = []

    def gestore(r):
        viste.append(r)
        if r.url.path.endswith("batch/read"):
            return httpx.Response(200, json={"results": [{"from": {"id": "7"}, "to": [{"toObjectId": 99, "associationTypes": []}]}]})
        if r.url.path == "/crm/v3/pipelines/deals":
            return httpx.Response(200, json={"results": [{"id": "default", "stages": [
                {"id": "a", "label": "Uno", "displayOrder": 1, "metadata": {"probability": "0.5", "isClosed": "false"}},
                {"id": "w", "label": "Vinta", "displayOrder": 2, "metadata": {"probability": "1.0", "isClosed": "true"}}]}]})
        return httpx.Response(200, json={})
    hs = _hs(gestore)
    assert hs.associazioni(CONTATTI, AZIENDE, [{"id": "7"}]) == {"7": ["99"]}
    assert viste[0].url.path == "/crm/v4/associations/contacts/companies/batch/read"
    hs.associa(OPPORTUNITA, "1", AZIENDE, "2")
    assert viste[1].method == "PUT" and viste[1].url.path == "/crm/v4/objects/deals/1/associations/default/companies/2"
    fasi = hs.fasi()
    assert [(f["id"], f["probabilita"], f["chiusa"], f["vinta"]) for f in fasi] == [("a", 0.5, False, False), ("w", 1.0, True, True)]


def test_trova_piu_risultati_e_ambiguo():
    risposta = {"results": [{"id": "1"}, {"id": "2"}]}
    assert _hs(lambda r: httpx.Response(200, json=risposta)).trova(AZIENDE, "nome", "Rossi") is False


def test_dominio():
    assert hubspot.dominio("https://www.Rossi.it/chi-siamo") == "rossi.it" and hubspot.dominio("rossi.it") == "rossi.it"
    assert hubspot.dominio("") == ""


# --- dall'esterno ad adabox ----------------------------------------------------------------------------------------

def test_import_aziende_persone_opportunita_con_associazioni(esterno, azienda):
    _, az, tr = _cliente(esterno)
    testo = sincronia.giro(esterno.pk)
    assert "Creati 1" in testo and "aziende: create 1" in testo and "opportunità: create 1" in testo
    ditta = riferimenti.trova(Contatto, azienda, "hubspot", sincronia.chiave_azienda(az.id_esterno))
    assert ditta.tipo == Contatto.AZIENDA and ditta.nome == "Verdi Srl" and ditta.sito == "https://verdi.it" and ditta.citta == "Bergamo"
    persona = Contatto.objects.get(tipo=Contatto.PERSONA)
    assert persona.societa == ditta
    o = riferimenti.trova(Opportunita, azienda, "hubspot", tr.id_esterno)
    assert o.titolo == "Impianto nuovo" and o.valore_atteso == Decimal("12500.50") and o.contatto == ditta
    assert o.chiusura_prevista.isoformat() == "2026-12-15" and o.fase.nome == "Proposta" and o.stato == Opportunita.APERTA


def test_stesso_numero_per_persona_e_azienda_non_si_confonde(esterno, azienda):
    prova.scrivi(esterno, {"firstname": "Anna", "email": "a@x.it"}, id_esterno="5")
    prova.scrivi(esterno, {"name": "Cinque Srl"}, id_esterno="5", tipo=AZIENDE)
    sincronia.giro(esterno.pk)
    assert riferimenti.trova(Contatto, azienda, "hubspot", "5").tipo == Contatto.PERSONA
    assert riferimenti.trova(Contatto, azienda, "hubspot", sincronia.chiave_azienda("5")).nome == "Cinque Srl"


def test_fase_vinta_e_persa(esterno, azienda):
    _, _, tr = _cliente(esterno, fase="closedwon")
    sincronia.giro(esterno.pk)
    o = Opportunita.objects.get()
    assert o.stato == Opportunita.VINTA and o.fase.vinta and o.chiusa_il
    prova.scrivi(esterno, {"dealstage": "closedlost"}, tr.id_esterno, OPPORTUNITA)
    assert "opportunità: create 0, aggiornate 1" in sincronia.giro(esterno.pk)
    o.refresh_from_db()
    assert o.stato == Opportunita.PERSA and not o.fase.vinta
    prova.scrivi(esterno, {"dealstage": "qualifiedtobuy"}, tr.id_esterno, OPPORTUNITA)
    sincronia.giro(esterno.pk)
    o.refresh_from_db()
    assert o.stato == Opportunita.APERTA and o.chiusa_il is None and o.fase.nome == "Qualificata"


def test_fase_con_lo_stesso_nome_vince_sulla_probabilita():
    FaseCrm.objects.create(nome="Contract sent", ordine=50, probabilita=20)
    fase, stato = sincronia.fase_in_adabox({"id": "contractsent", "label": "Contract sent", "probabilita": 0.9, "chiusa": False})
    assert fase.nome == "Contract sent" and stato == Opportunita.APERTA


def test_azienda_omonima_si_aggancia_una_sola(esterno, azienda):
    gia = Contatto.objects.create(azienda=azienda, nome="verdi srl", tipo=Contatto.AZIENDA, partita_iva="123")
    prova.scrivi(esterno, {"name": "Verdi Srl", "city": "Bergamo"}, tipo=AZIENDE)
    sincronia.giro(esterno.pk)
    gia.refresh_from_db()
    assert Contatto.objects.filter(tipo=Contatto.AZIENDA).count() == 1 and gia.partita_iva == "123" and gia.citta == "Bergamo"
    Contatto.objects.create(azienda=azienda, nome="Gialli Spa", tipo=Contatto.AZIENDA)
    Contatto.objects.create(azienda=azienda, nome="Gialli Spa", tipo=Contatto.AZIENDA)
    prova.scrivi(esterno, {"name": "Gialli Spa"}, tipo=AZIENDE)
    assert "saltate 1" in sincronia.giro(esterno.pk)


def test_senza_aziende_e_opportunita_passano_solo_le_persone(esterno, azienda):
    esterno.aziende = esterno.opportunita = False
    esterno.save()
    _cliente(esterno)
    sincronia.giro(esterno.pk)
    assert list(Contatto.objects.values_list("tipo", flat=True)) == [Contatto.PERSONA] and not Opportunita.objects.exists()
    assert Contatto.objects.get().societa is None


def test_i_cursori_sono_per_tipo(esterno, azienda):
    _cliente(esterno)
    sincronia.giro(esterno.pk)
    esterno.refresh_from_db()
    assert esterno.cursore and set(esterno.cursori) == {AZIENDE, OPPORTUNITA}


def test_ciò_che_arriva_non_riparte(azienda, esterno, django_capture_on_commit_callbacks):
    from core.models import Lavoro
    _cliente(esterno)
    with django_capture_on_commit_callbacks(execute=True):
        sincronia.giro(esterno.pk)
    assert not Lavoro.objects.filter(funzione__startswith="connettori.sincronia.scrivi").exists()


# --- da adabox all'esterno -----------------------------------------------------------------------------------------

def _salva(django_capture_on_commit_callbacks, modello, **campi):
    with django_capture_on_commit_callbacks(execute=True):
        return modello.objects.create(**campi)


def test_azienda_e_persona_partono_associate(adabox, azienda, django_capture_on_commit_callbacks):
    ditta = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Rossi Srl", tipo=Contatto.AZIENDA,
                   sito="https://www.rossi.it")
    persona = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Mario Rossi", email="m@rossi.it",
                     tipo=Contatto.PERSONA, societa=ditta)
    r_az = RecordProva.objects.get(tipo=AZIENDE)
    r_p = RecordProva.objects.get(tipo=CONTATTI)
    assert r_az.proprieta["name"] == "Rossi Srl" and r_az.proprieta["domain"] == "rossi.it"
    assert r_p.associazioni[AZIENDE] == [r_az.id_esterno]
    assert riferimenti.id_esterno(ditta, "hubspot") == sincronia.chiave_azienda(r_az.id_esterno)
    assert riferimenti.id_esterno(persona, "hubspot") == r_p.id_esterno


def test_azienda_gia_presente_di_la_per_dominio(adabox, azienda, django_capture_on_commit_callbacks):
    r = prova.scrivi(adabox, {"name": "Rossi S.r.l.", "domain": "rossi.it"}, tipo=AZIENDE)
    ditta = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Rossi Srl", tipo=Contatto.AZIENDA, sito="rossi.it")
    assert RecordProva.objects.filter(tipo=AZIENDE).count() == 1
    assert riferimenti.id_esterno(ditta, "hubspot") == sincronia.chiave_azienda(r.id_esterno)


def test_azienda_ambigua_di_la_si_segnala(adabox, azienda, django_capture_on_commit_callbacks):
    prova.scrivi(adabox, {"name": "Bianchi"}, tipo=AZIENDE)
    prova.scrivi(adabox, {"name": "Bianchi"}, tipo=AZIENDE)
    ditta = Contatto.objects.create(azienda=azienda, nome="Bianchi", tipo=Contatto.AZIENDA)
    assert "più aziende" in sincronia.scrivi_fuori(adabox.pk, ditta.pk)
    adabox.refresh_from_db()
    assert adabox.in_errore and RecordProva.objects.filter(tipo=AZIENDE).count() == 2


def test_opportunita_parte_nella_fase_giusta_e_associata(adabox, azienda, django_capture_on_commit_callbacks):
    ditta = _salva(django_capture_on_commit_callbacks, Contatto, azienda=azienda, nome="Rossi Srl", tipo=Contatto.AZIENDA)
    o = _salva(django_capture_on_commit_callbacks, Opportunita, azienda=azienda, titolo="Rinnovo", contatto=ditta,
               valore_atteso=Decimal("3000"), fase=FaseCrm.objects.get(nome="Negoziazione"))
    r = RecordProva.objects.get(tipo=OPPORTUNITA)
    assert r.proprieta["dealname"] == "Rinnovo" and r.proprieta["amount"] == "3000.00" and r.proprieta["dealstage"] == "decisionmakerboughtin"
    assert r.associazioni[AZIENDE] == [RecordProva.objects.get(tipo=AZIENDE).id_esterno]
    with django_capture_on_commit_callbacks(execute=True):
        o.fase = FaseCrm.objects.get(vinta=True)
        o.save()
    r.refresh_from_db()
    assert r.proprieta["dealstage"] == "closedwon" and RecordProva.objects.filter(tipo=OPPORTUNITA).count() == 1


def test_opportunita_con_persona_associa_anche_la_sua_azienda(adabox, azienda, django_capture_on_commit_callbacks):
    ditta = Contatto.objects.create(azienda=azienda, nome="Neri Spa", tipo=Contatto.AZIENDA)
    persona = Contatto.objects.create(azienda=azienda, nome="Luca Neri", email="l@neri.it", tipo=Contatto.PERSONA, societa=ditta)
    RecordProva.objects.all().delete()
    o = Opportunita.objects.create(azienda=azienda, titolo="Prova", contatto=persona)
    assert sincronia.scrivi_opportunita(adabox.pk, o.pk) == "scritto"
    r = RecordProva.objects.get(tipo=OPPORTUNITA)
    assert set(r.associazioni) == {AZIENDE, CONTATTI}


def test_ricalcoli_periodici_non_ripartono(adabox, azienda, django_capture_on_commit_callbacks):
    from core.models import Lavoro
    o = Opportunita.objects.create(azienda=azienda, titolo="X")
    Lavoro.objects.all().delete()
    with django_capture_on_commit_callbacks(execute=True):
        o.punteggio = 40
        o.save(update_fields=["punteggio", "punteggio_il"])
    assert not Lavoro.objects.filter(funzione="connettori.sincronia.scrivi_opportunita").exists()


def test_opportunita_esclusa_non_parte(adabox, azienda, django_capture_on_commit_callbacks):
    adabox.opportunita = False
    adabox.save()
    _salva(django_capture_on_commit_callbacks, Opportunita, azienda=azienda, titolo="Rinnovo")
    assert not RecordProva.objects.filter(tipo=OPPORTUNITA).exists()
