"""HubSpot: formato delle chiamate, errori, sincronia nei due versi, nessun rimbalzo, nessun dato perso."""
import json

import httpx2 as httpx
import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from connettori import eventi, riferimenti, sincronia
from connettori.forms import CollegamentoForm
from connettori.models import CollegamentoEsterno, ConsegnaWebhook, RecordProva, RiferimentoEsterno, Webhook
from connettori.sistemi import hubspot, prova
from connettori.sistemi.base import ErroreConnettore, ErroreTemporaneo
from contatti.models import Contatto
from core import cifratura
from core.models import Azienda, Lavoro, Sequenza

pytestmark = pytest.mark.django_db


@pytest.fixture
def azienda():
    a = Azienda.objects.first()
    Sequenza.objects.get_or_create(codice="contatti.contatto", azienda=a, defaults={"formato": "C{numero:05d}"})
    return a


@pytest.fixture
def esterno(azienda):
    return CollegamentoEsterno.objects.create(azienda=azienda, comanda=CollegamentoEsterno.ESTERNO)


@pytest.fixture
def adabox(azienda):
    return CollegamentoEsterno.objects.create(azienda=azienda, comanda=CollegamentoEsterno.ADABOX)


def _hs(gestore):
    return hubspot.HubSpot("segreto", transport=httpx.MockTransport(gestore))


def test_chiamata_di_ricerca_nel_formato_di_hubspot():
    viste = []

    def gestore(r):
        viste.append(r)
        return httpx.Response(200, json={"results": [{"id": "1", "properties": {}}], "paging": {"next": {"after": "100"}}})
    record, dopo = _hs(gestore).modificati_da(1234, "50")
    r = viste[0]
    corpo = json.loads(r.content)
    assert str(r.url) == "https://api.hubapi.com/crm/v3/objects/contacts/search" and r.headers["Authorization"] == "Bearer segreto"
    assert corpo["filterGroups"][0]["filters"][0] == {"propertyName": "lastmodifieddate", "operator": "GTE", "value": "1234"}
    assert corpo["sorts"][0] == {"propertyName": "lastmodifieddate", "direction": "ASCENDING"} and corpo["after"] == "50" and corpo["limit"] <= 200
    assert dopo == "100" and record[0]["id"] == "1"


@pytest.mark.parametrize("stato,errore", [(429, ErroreTemporaneo), (503, ErroreTemporaneo), (401, ErroreConnettore), (400, ErroreConnettore)])
def test_errori_temporanei_e_definitivi(stato, errore):
    with pytest.raises(errore) as e:
        _hs(lambda r: httpx.Response(stato, json={"message": "no"})).verifica()
    assert isinstance(e.value, ErroreTemporaneo) == (errore is ErroreTemporaneo)


def test_rete_giu_e_temporaneo():
    def gestore(r):
        raise httpx.ConnectError("giù")
    with pytest.raises(ErroreTemporaneo):
        _hs(gestore).verifica()


def test_il_token_non_finisce_nei_messaggi_di_errore():
    with pytest.raises(ErroreConnettore) as e:
        _hs(lambda r: httpx.Response(401, json={})).verifica()
    assert "segreto" not in str(e.value)


def test_nome_e_campi_nei_due_versi():
    dati = hubspot.in_adabox({"id": "1", "properties": {"firstname": "Mario", "lastname": "Rossi", "email": "M@X.it", "phone": "", "city": None}})
    assert dati == {"nome": "Mario Rossi", "email": "m@x.it"}
    c = Contatto(nome="Maria Grazia Rossi", email="m@x.it", telefono="1")
    assert hubspot.in_hubspot(c) == {"email": "m@x.it", "firstname": "Maria", "lastname": "Grazia Rossi", "phone": "1"}


def test_import_crea_e_collega(esterno, azienda):
    r = prova.scrivi(esterno, {"firstname": "Mario", "lastname": "Rossi", "email": "m@x.it", "phone": "02"})
    assert "Creati 1" in sincronia.giro(esterno.pk)
    c = riferimenti.trova(Contatto, azienda, "hubspot", r.id_esterno)
    assert c.nome == "Mario Rossi" and c.telefono == "02" and c.tipo == Contatto.PERSONA and c.codice and c.azienda == azienda


def test_rileggere_non_duplica_e_non_salva_a_vuoto(esterno):
    prova.scrivi(esterno, {"firstname": "Mario", "email": "m@x.it"})
    sincronia.giro(esterno.pk)
    assert "uguali 1" in sincronia.giro(esterno.pk)                   # il margine rilegge: nessun doppione
    assert Contatto.objects.count() == 1


def test_modifica_esterna_arriva(esterno, azienda):
    r = prova.scrivi(esterno, {"firstname": "Mario", "email": "m@x.it"})
    sincronia.giro(esterno.pk)
    prova.scrivi(esterno, {"jobtitle": "Titolare"}, r.id_esterno)
    assert "aggiornati 1" in sincronia.giro(esterno.pk)
    assert Contatto.objects.get().ruolo == "Titolare"


def test_un_campo_vuoto_non_cancella_il_valore(esterno):
    r = prova.scrivi(esterno, {"firstname": "Mario", "email": "m@x.it", "phone": "02"})
    sincronia.giro(esterno.pk)
    prova.scrivi(esterno, {"phone": ""}, r.id_esterno)
    sincronia.giro(esterno.pk)
    assert Contatto.objects.get().telefono == "02"


def test_si_aggancia_al_contatto_con_la_stessa_email(esterno, azienda):
    c = Contatto.objects.create(azienda=azienda, nome="Già qui", email="M@x.it", partita_iva="123")
    r = prova.scrivi(esterno, {"firstname": "Mario", "email": "m@x.it"})
    sincronia.giro(esterno.pk)
    assert Contatto.objects.count() == 1 and riferimenti.id_esterno(c, "hubspot") == r.id_esterno
    c.refresh_from_db()
    assert c.nome == "Mario" and c.partita_iva == "123"


def test_due_contatti_con_la_stessa_email_si_salta_e_si_dice(esterno, azienda):
    Contatto.objects.create(azienda=azienda, nome="A", email="m@x.it")
    Contatto.objects.create(azienda=azienda, nome="B", email="m@x.it")
    prova.scrivi(esterno, {"firstname": "Mario", "email": "m@x.it"})
    assert "saltati 1" in sincronia.giro(esterno.pk)
    assert not RiferimentoEsterno.objects.exists() and Contatto.objects.count() == 2


def test_un_altra_azienda_non_si_tocca(esterno, azienda):
    altra = Azienda.objects.create(nome="Altra")
    c = Contatto.objects.create(azienda=altra, nome="Altrui", email="m@x.it")
    prova.scrivi(esterno, {"firstname": "Mario", "email": "m@x.it"})
    sincronia.giro(esterno.pk)
    c.refresh_from_db()
    assert c.nome == "Altrui" and Contatto.objects.filter(azienda=azienda).count() == 1


def test_il_cursore_avanza_e_tiene_un_margine(esterno, monkeypatch):
    prova.scrivi(esterno, {"firstname": "Mario", "email": "m@x.it"})
    sincronia.giro(esterno.pk)
    esterno.refresh_from_db()
    assert esterno.cursore is not None
    letti = []
    originale = hubspot.HubSpot.modificati_da
    monkeypatch.setattr(hubspot.HubSpot, "modificati_da", lambda self, ms, dopo=None: letti.append(ms) or originale(self, ms, dopo))
    sincronia.giro(esterno.pk)
    assert letti[0] == int((esterno.cursore - sincronia.MARGINE).timestamp() * 1000)


def test_paginazione(esterno, monkeypatch):
    monkeypatch.setattr(hubspot, "PER_PAGINA", 2)
    for i in range(5):
        prova.scrivi(esterno, {"firstname": f"N{i}", "email": f"n{i}@x.it"})
    assert "Creati 5" in sincronia.giro(esterno.pk)


def test_token_sbagliato_si_vede_e_non_ritenta(esterno, monkeypatch):
    monkeypatch.setattr(hubspot.HubSpot, "modificati_da", lambda *a, **k: (_ for _ in ()).throw(ErroreConnettore("rifiuta il token")))
    assert "token" in sincronia.giro(esterno.pk)
    esterno.refresh_from_db()
    assert esterno.in_errore and "token" in esterno.ultimo_esito


def test_errore_temporaneo_si_rilancia_per_ritentare(esterno, monkeypatch):
    monkeypatch.setattr(hubspot.HubSpot, "modificati_da", lambda *a, **k: (_ for _ in ()).throw(ErroreTemporaneo("429")))
    with pytest.raises(ErroreTemporaneo):
        sincronia.giro(esterno.pk)


def test_vero_senza_token_si_ferma_prima_di_chiamare(azienda):
    c = CollegamentoEsterno.objects.create(azienda=azienda, modalita=CollegamentoEsterno.VERA)
    with pytest.raises(ErroreConnettore):
        sincronia.client(c)


def test_quando_comanda_adabox_la_lettura_non_scrive(adabox):
    prova.scrivi(adabox, {"firstname": "Mario", "email": "m@x.it"})
    assert sincronia.giro(adabox.pk) is None and not Contatto.objects.exists()


def _salva(azienda, django_capture_on_commit_callbacks, **campi):
    with django_capture_on_commit_callbacks(execute=True):
        return Contatto.objects.create(azienda=azienda, **campi)


def test_contatto_di_adabox_parte_e_si_collega(adabox, azienda, django_capture_on_commit_callbacks):
    c = _salva(azienda, django_capture_on_commit_callbacks, nome="Mario Rossi", email="m@x.it", tipo=Contatto.PERSONA, telefono="02")
    r = RecordProva.objects.get()
    assert r.proprieta["firstname"] == "Mario" and r.proprieta["phone"] == "02" and riferimenti.id_esterno(c, "hubspot") == r.id_esterno


def test_la_modifica_aggiorna_lo_stesso_record(adabox, azienda, django_capture_on_commit_callbacks):
    c = _salva(azienda, django_capture_on_commit_callbacks, nome="Mario", email="m@x.it", tipo=Contatto.PERSONA)
    with django_capture_on_commit_callbacks(execute=True):
        c.ruolo = "Titolare"
        c.save()
    assert RecordProva.objects.count() == 1 and RecordProva.objects.get().proprieta["jobtitle"] == "Titolare"


def test_email_gia_presente_di_la_non_crea_un_doppione(adabox, azienda, django_capture_on_commit_callbacks):
    r = prova.scrivi(adabox, {"email": "m@x.it", "firstname": "Vecchio"})
    c = _salva(azienda, django_capture_on_commit_callbacks, nome="Mario", email="M@x.it", tipo=Contatto.PERSONA)
    assert RecordProva.objects.count() == 1 and riferimenti.id_esterno(c, "hubspot") == r.id_esterno


def test_senza_email_o_azienda_non_parte(adabox, azienda, django_capture_on_commit_callbacks):
    _salva(azienda, django_capture_on_commit_callbacks, nome="Senza email", tipo=Contatto.PERSONA)
    _salva(azienda, django_capture_on_commit_callbacks, nome="Rossi Srl", email="r@x.it", tipo=Contatto.AZIENDA)
    assert not RecordProva.objects.exists()


def test_altra_azienda_non_parte(adabox, django_capture_on_commit_callbacks):
    altra = Azienda.objects.create(nome="Altra")
    _salva(altra, django_capture_on_commit_callbacks, nome="X", email="x@x.it", tipo=Contatto.PERSONA)
    assert not RecordProva.objects.exists()


def test_ciò_che_arriva_non_rimbalza(azienda, esterno, django_capture_on_commit_callbacks):
    Webhook.objects.create(azienda=azienda, nome="W", url="https://x.example.com/", eventi="*")
    prova.scrivi(esterno, {"firstname": "Mario", "email": "m@x.it"})
    with django_capture_on_commit_callbacks(execute=True):
        sincronia.giro(esterno.pk)
    assert Contatto.objects.count() == 1 and not ConsegnaWebhook.objects.exists()
    assert not Lavoro.objects.filter(funzione="connettori.sincronia.scrivi_fuori").exists()


def test_passare_al_vero_azzera_i_dati_di_prova(esterno, azienda):
    r = prova.scrivi(esterno, {"firstname": "Mario", "email": "m@x.it"})
    sincronia.giro(esterno.pk)
    esterno.refresh_from_db()
    form = CollegamentoForm(data={"sistema": "hubspot", "modalita": "vera", "comanda": "esterno", "attivo": "on", "nuovo_token": "pat-1"}, instance=esterno)
    assert form.is_valid(), form.errors
    form.save()
    esterno.refresh_from_db()
    assert esterno.cursore is None and not RiferimentoEsterno.objects.exists() and r.id_esterno
    assert esterno.token() == "pat-1" and "pat-1" not in esterno.token_cifrato and cifratura.decifra(esterno.token_cifrato) == "pat-1"


def test_vero_senza_token_il_form_lo_dice(azienda):
    assert "nuovo_token" in CollegamentoForm(data={"sistema": "hubspot", "modalita": "vera", "comanda": "esterno", "attivo": "on"}).errors


def _root(azienda):
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([azienda])
    root.profilo.azienda_predefinita = azienda
    root.profilo.save()
    return root


def test_dalla_pagina_si_prova_tutto(client, esterno, azienda):
    client.force_login(_root(azienda))
    base = f"/connettori/collegamenti/{esterno.pk}/"
    assert client.get(base).status_code == 200
    assert client.post(base + "bottone/simula_nuovo/").status_code == 302 and RecordProva.objects.count() == 1
    assert client.post(base + "bottone/verifica/").status_code == 302
    assert client.post(base + "bottone/sincronizza/").status_code == 302
    assert Contatto.objects.count() == 1
    assert "Contatti collegati: 1" in client.get(base).content.decode()
    assert client.post(base + "bottone/simula_modifica/").status_code == 302


def test_il_token_non_compare_nella_pagina(client, azienda):
    c = CollegamentoEsterno.objects.create(azienda=azienda, modalita=CollegamentoEsterno.VERA, token_cifrato=cifratura.cifra("pat-segretissimo"))
    client.force_login(_root(azienda))
    assert "pat-segretissimo" not in client.get(f"/connettori/collegamenti/{c.pk}/").content.decode()
    assert "pat-segretissimo" not in client.get(f"/connettori/collegamenti/{c.pk}/modifica/").content.decode()


def test_un_solo_collegamento_per_azienda_dalla_pagina(client, esterno, azienda):
    client.force_login(_root(azienda))
    assert client.get("/connettori/collegamenti/nuovo/").status_code == 403


def test_collegamento_di_altra_azienda_non_si_apre(client, azienda):
    altra = Azienda.objects.create(nome="Altra")
    c = CollegamentoEsterno.objects.create(azienda=altra)
    client.force_login(_root(azienda))
    assert client.get(f"/connettori/collegamenti/{c.pk}/").status_code == 404
    assert client.post(f"/connettori/collegamenti/{c.pk}/bottone/sincronizza/").status_code == 404


def test_il_cron_accoda_un_lavoro_per_collegamento(esterno, azienda):
    Lavoro.objects.all().delete()
    sincronia.giro_di_tutti()
    assert Lavoro.objects.filter(funzione="connettori.sincronia.giro").count() == 1
    assert timezone.now() and eventi.muto() is False
