"""Odoo: API JSON-2, un account per utente con le sue regole di Odoo, visibilità in adabox per utente, aggancio per
partita IVA e per nome dentro l'azienda, venditore che diventa commerciale."""
import json
from pathlib import Path

import httpx2 as httpx
import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.test import RequestFactory

import crm
from connettori import riferimenti, sincronia
from connettori.forms import CollegamentoForm
from connettori.models import AccountEsterno, CollegamentoEsterno, VisibilitaEsterna
from connettori.sistemi import odoo
from connettori.sistemi import prova_odoo as finto
from connettori.sistemi.base import AZIENDE, OPPORTUNITA, PERSONE, ErroreConnettore
from contatti.models import Contatto
from core import cifratura, regole
from core.models import Azienda, Sequenza
from core.viste import registry
from crm.models import Opportunita

pytestmark = pytest.mark.django_db
OD = CollegamentoEsterno.ODOO


def _utente(nome, azienda, *permessi):
    u = User.objects.create_user(nome, f"{nome}@x.it", "x")
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_opportunita", "view_contatto", *permessi]))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def s(db):
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    Sequenza.objects.get_or_create(codice="contatti.contatto", azienda=azienda, defaults={"formato": "C{numero:05d}"})
    c = CollegamentoEsterno.objects.create(azienda=azienda, sistema=OD, comanda=CollegamentoEsterno.ESTERNO, per_utente=True)
    mario, lucia, capo = _utente("mario", azienda), _utente("lucia", azienda), _utente("capo", azienda)
    conti = {}
    for u, uid in ((mario, 28), (lucia, 29)):
        conti[u.username] = AccountEsterno.objects.create(collegamento=c, utente=u, id_utente_esterno=str(uid),
                                                          chiave_cifrata=cifratura.cifra(finto.chiave(uid)))
    verdi = finto.scrivi(c, {"name": "Verdi Srl", "vat": "IT01234567897", "city": "Bergamo"}, "38", AZIENDE)
    anna = finto.scrivi(c, {"name": "Anna Verdi", "email": "anna@verdi.it", "parent_id": 38, "function": "Acquisti"}, "39", PERSONE)
    finto.scrivi(c, {"name": "Impianto (di Mario)", "expected_revenue": 12500.0, "stage_id": 2, "user_id": 28, "partner_id": 39}, "1", OPPORTUNITA)
    finto.scrivi(c, {"name": "Manutenzione (di Lucia)", "expected_revenue": 3000.0, "stage_id": 1, "user_id": 29, "partner_id": 38}, "2", OPPORTUNITA)
    finto.scrivi(c, {"name": "Persa (di Lucia)", "stage_id": 3, "user_id": 29, "partner_id": 38, "perso": True}, "3", OPPORTUNITA)
    return {"azienda": azienda, "c": c, "mario": mario, "lucia": lucia, "capo": capo, "conti": conti, "verdi": verdi, "anna": anna}


def _giro(s, *chi):
    for nome in chi:
        assert "Creati" in sincronia.giro_account(s["conti"][nome].pk), nome


def _vede(utente, azienda, modello=Opportunita):
    request = RequestFactory().get("/")
    request.user, request.azienda = utente, azienda
    return set(registry.per_modello(modello).get_queryset(request).values_list("titolo" if modello is Opportunita else "nome", flat=True))


# --- il client ---------------------------------------------------------------------------------------------------------

def test_chiamate_json2_con_bearer_e_database():
    viste = []

    def gestore(r):
        viste.append(r)
        return httpx.Response(200, json={"uid": 7})
    assert odoo.Odoo("https://acme.odoo.com", "acme", "chiave", transport=httpx.MockTransport(gestore)).utente() == "7"
    r = viste[0]
    assert str(r.url) == "https://acme.odoo.com/json/2/res.users/context_get"
    assert r.headers["Authorization"] == "bearer chiave" and r.headers["X-Odoo-Database"] == "acme" and json.loads(r.content) == {}


@pytest.mark.parametrize("stato,corpo,messaggio", [
    (401, {"name": "werkzeug.exceptions.Unauthorized"}, "chiave API"),
    (403, {"name": "odoo.exceptions.AccessError", "message": "Aiaiai! record segreti"}, "nega l'accesso"),
    (404, {"name": "werkzeug.exceptions.NotFound"}, "non conosce"),
])
def test_errori_di_odoo(stato, corpo, messaggio):
    sistema = odoo.Odoo("https://acme.odoo.com", "", "k", transport=httpx.MockTransport(lambda r: httpx.Response(stato, json=corpo)))
    with pytest.raises(ErroreConnettore, match=messaggio):
        sistema.utente()


def test_i_campi_vuoti_di_odoo_non_diventano_false():
    dati = odoo.Odoo("https://x", "", "k").in_adabox(AZIENDE, {"name": "Verdi", "phone": False, "vat": "IT01234567897", "city": False})
    assert dati == {"nome": "Verdi", "partita_iva": "IT01234567897"}


# --- un account per utente e la visibilità -------------------------------------------------------------------------------

def test_ognuno_vede_in_adabox_cio_che_vede_in_odoo(s):
    _giro(s, "mario", "lucia")
    assert Opportunita.objects.count() == 3                                     # un record solo anche se lo vedono in due
    assert _vede(s["mario"], s["azienda"]) == {"Impianto (di Mario)"}
    assert _vede(s["lucia"], s["azienda"]) == {"Impianto (di Mario)", "Manutenzione (di Lucia)", "Persa (di Lucia)"}
    assert _vede(s["capo"], s["azienda"]) == set()                              # senza account non vede i dati di Odoo
    Opportunita.objects.create(azienda=s["azienda"], titolo="Nata in adabox")
    assert _vede(s["capo"], s["azienda"]) == {"Nata in adabox"}                  # le altre seguono le regole di sempre
    capo = User.objects.get(pk=s["capo"].pk)
    capo.user_permissions.add(Permission.objects.get(codename="vede_tutti_i_dati_esterni"))
    assert len(_vede(User.objects.get(pk=capo.pk), s["azienda"])) == 4


def test_venditore_commerciale_persa_e_cliente(s):
    _giro(s, "mario", "lucia")
    mia = Opportunita.objects.get(titolo="Impianto (di Mario)")
    ditta = Contatto.objects.get(tipo=Contatto.AZIENDA)
    assert mia.commerciale == s["mario"] and mia.contatto == ditta and mia.fase.nome == "Proposta"           # «Qualified» 50%: la più vicina è 60%
    assert Opportunita.objects.get(titolo="Persa (di Lucia)").stato == Opportunita.PERSA
    assert Opportunita.objects.get(titolo="Manutenzione (di Lucia)").commerciale == s["lucia"]
    anna = Contatto.objects.get(tipo=Contatto.PERSONA)
    assert anna.societa == ditta and anna.ruolo == "Acquisti" and anna.partita_iva == ""         # la partita IVA ereditata no
    assert ditta.partita_iva == "01234567897" and ditta.nazione == "IT"
    assert not Contatto.objects.filter(nome__in=["Mario Venditore", "Lucia Responsabile", "Azienda dell'istanza"]).exists()


def test_la_visibilita_segue_odoo_quando_cambia(s):
    _giro(s, "mario")
    assert _vede(s["mario"], s["azienda"]) == {"Impianto (di Mario)"}
    finto.scrivi(s["c"], {"user_id": 29}, "1", OPPORTUNITA)                         # riassegnata a Lucia in Odoo
    assert "non più visibili 1" in sincronia.giro_account(s["conti"]["mario"].pk)
    assert _vede(s["mario"], s["azienda"]) == set()
    assert not VisibilitaEsterna.objects.filter(account=s["conti"]["mario"]).filter(riferimento__content_type__model="opportunita").exists()


def test_azienda_agganciata_per_partita_iva_e_persona_per_nome_nell_azienda(s):
    gia = Contatto.objects.create(azienda=s["azienda"], codice="C1", nome="Verdi S.r.l.", tipo=Contatto.AZIENDA, partita_iva="01234567897")
    anna = Contatto.objects.create(azienda=s["azienda"], codice="C2", nome="anna verdi", tipo=Contatto.PERSONA, societa=gia)
    omonima = Contatto.objects.create(azienda=s["azienda"], codice="C3", nome="Anna Verdi", tipo=Contatto.PERSONA)   # senza azienda: non è lei
    finto.scrivi(s["c"], {"email": False}, "39", PERSONE)
    _giro(s, "lucia")
    assert Contatto.objects.filter(tipo=Contatto.AZIENDA).count() == 1
    assert riferimenti.id_esterno(gia, OD) == sincronia.chiave_azienda("38")
    assert riferimenti.id_esterno(anna, OD) == "39" and riferimenti.id_esterno(omonima, OD) is None


def test_stessa_partita_iva_su_due_contatti_non_si_sceglie(s):
    for i in (1, 2):
        Contatto.objects.create(azienda=s["azienda"], codice=f"C{i}", nome=f"Verdi {i}", tipo=Contatto.AZIENDA, partita_iva="01234567897")
    testo = sincronia.giro_account(s["conti"]["lucia"].pk)
    assert "saltate 1" in testo and Contatto.objects.filter(tipo=Contatto.AZIENDA).count() == 2


def test_il_cron_accoda_un_giro_per_account(s):
    from core.models import Lavoro
    Lavoro.objects.all().delete()
    sincronia.giro_di_tutti()
    assert Lavoro.objects.filter(funzione="connettori.sincronia.giro_account").count() == 2
    assert not Lavoro.objects.filter(funzione="connettori.sincronia.giro").exists()


def test_un_filtro_rotto_nasconde_tutto(s, monkeypatch):
    def rotto(vista, request, qs):
        raise RuntimeError("boom")
    monkeypatch.setattr(regole, "_FILTRI", [*regole._FILTRI, rotto])
    Opportunita.objects.create(azienda=s["azienda"], titolo="Nata in adabox")
    assert _vede(s["capo"], s["azienda"]) == set()


# --- pagine e modulo -----------------------------------------------------------------------------------------------------

def test_ognuno_collega_il_suo_account_dalla_pagina(client, s):
    nuovo = _utente("nuovo", s["azienda"])
    client.force_login(nuovo)
    assert "Odoo" in client.get("/connettori/account/").content.decode()
    client.post(f"/connettori/account/{s['c'].pk}/collega/", {"chiave": "sbagliata"})
    assert not AccountEsterno.objects.filter(utente=nuovo).exists()
    client.post(f"/connettori/account/{s['c'].pk}/collega/", {"chiave": finto.chiave(28)})          # l'account di Mario
    assert not AccountEsterno.objects.filter(utente=nuovo).exists()
    client.post(f"/connettori/account/{s['c'].pk}/collega/", {"chiave": finto.chiave(2)})
    voce = AccountEsterno.objects.get(utente=nuovo)
    assert voce.id_utente_esterno == "2" and voce.chiave() == finto.chiave(2) and finto.chiave(2) not in voce.chiave_cifrata
    assert "Collegato" in client.get("/connettori/account/").content.decode()
    client.post(f"/connettori/account/{voce.pk}/scollega/")
    assert not AccountEsterno.objects.filter(utente=nuovo).exists()


def test_il_modulo_controlla_odoo_e_il_per_utente():
    base = {"modalita": "vera", "attivo": "on", "aziende": "on", "opportunita": "on"}
    f = CollegamentoForm(data={**base, "sistema": "hubspot", "comanda": "esterno", "per_utente": "on", "nuovo_token": "t"})
    assert "per_utente" in f.errors
    f = CollegamentoForm(data={**base, "sistema": OD, "comanda": "adabox", "per_utente": "on", "indirizzo": "https://acme.odoo.com"})
    assert "comanda" in f.errors
    f = CollegamentoForm(data={**base, "sistema": OD, "comanda": "esterno", "indirizzo": "http://acme.odoo.com:8069"})
    assert "indirizzo" in f.errors and "nuovo_token" in f.errors
    f = CollegamentoForm(data={**base, "sistema": OD, "comanda": "esterno", "per_utente": "on", "indirizzo": "https://acme.odoo.com/", "database": "acme"})
    assert f.is_valid(), f.errors
    assert f.cleaned_data["indirizzo"] == "https://acme.odoo.com"
