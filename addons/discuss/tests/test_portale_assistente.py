"""L'assistente nel portale clienti: risponde con la conoscenza pubblica, la guida e il riepilogo dei documenti del
cliente; nessun dato di altri clienti, niente strumenti, tetti e passaggio a una richiesta di assistenza."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from contatti.models import Contatto
from core.models import Azienda
from discuss import ia, portale_assistente
from discuss.assistente_sito import MARCATORE
from discuss.models import DomandaPortale, DomandaSenzaRisposta, Sportello, VoceConoscenza
from fatturazione.models import Fattura, Scadenza
from portale import sezioni
from portale.inviti import invita

pytestmark = pytest.mark.django_db


@pytest.fixture
def scena(db, monkeypatch, mailoutbox, django_capture_on_commit_callbacks):
    monkeypatch.setattr("ai.conoscenza.embedding", lambda testi, tipo="document": None)
    azienda = Azienda.objects.get(pk=1)
    rossi = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    anna = Contatto.objects.create(azienda=azienda, nome="Anna Rossi", tipo="persona", societa=rossi, email="anna@rossi.it")
    bianchi = Contatto.objects.create(azienda=azienda, nome="Bianchi Spa", cliente=True)
    interno = User.objects.create_superuser("sara", "sara@example.com", "x")
    with django_capture_on_commit_callbacks(execute=True):
        sportello = Sportello.objects.create(nome="Assistenza", modalita=Sportello.AI, nome_ai="Ada", portale=True, azienda=azienda)
        VoceConoscenza.objects.create(sportello=sportello, titolo="Resi", testo="I resi si chiedono entro 14 giorni dalla consegna.")
    for cliente, numero, residuo in ((rossi, "FT/1", "50.00"), (bianchi, "FT/ALTRUI", "999.00")):
        f = Fattura.objects.create(azienda=azienda, cliente=cliente, numero=numero)
        Fattura.objects.filter(pk=f.pk).update(stato=Fattura.EMESSA, totale=Decimal("122.00"))
        Scadenza.objects.create(fattura=f, data=datetime.date(2026, 12, 31), importo=Decimal(residuo))
    accesso = invita(anna, interno)
    return {"azienda": azienda, "rossi": rossi, "accesso": accesso, "sportello": sportello, "interno": interno}


@pytest.fixture
def modello(monkeypatch):
    stato = {"risposta": "Hai una fattura da pagare, la FT/1.", "chiamate": []}

    def genera(sistema, testo, utente, azienda=None, titolo="", di_servizio=False):
        stato["chiamate"].append({"sistema": sistema, "testo": testo, "utente": utente, "azienda": azienda, "di_servizio": di_servizio})
        if isinstance(stato["risposta"], Exception):
            raise stato["risposta"]
        return stato["risposta"]
    monkeypatch.setattr(ia, "genera", genera)
    return stato


def test_la_sezione_c_e_solo_con_uno_sportello_abilitato(scena):
    assert "assistente" in [s["chiave"] for s in sezioni.per(scena["accesso"])]
    Sportello.objects.filter(pk=scena["sportello"].pk).update(portale=False)
    assert "assistente" not in [s["chiave"] for s in sezioni.per(scena["accesso"])]
    Sportello.objects.filter(pk=scena["sportello"].pk).update(portale=True, modalita=Sportello.PERSONE)   # senza AI
    assert "assistente" not in [s["chiave"] for s in sezioni.per(scena["accesso"])]


def test_risponde_con_la_conoscenza_e_i_soli_dati_del_cliente(client, scena, modello):
    client.force_login(scena["accesso"].utente)
    r = client.post(reverse("discuss:portale_assistente"), {"domanda": "Ho fatture da pagare? E come funzionano i resi?"})
    assert r.status_code == 302
    chiamata, = modello["chiamate"]
    assert "FT/1" in chiamata["sistema"] and "FT/ALTRUI" not in chiamata["sistema"] and "999" not in chiamata["sistema"]
    assert "entro 14 giorni" in chiamata["sistema"] and "Anna Rossi" in chiamata["sistema"]
    assert chiamata["di_servizio"] and chiamata["azienda"] == scena["azienda"]
    voce = DomandaPortale.objects.get()
    assert voce.cliente == scena["rossi"] and voce.risposta == "Hai una fattura da pagare, la FT/1." and voce.fonti == ["Resi"]
    pagina = client.get(reverse("discuss:portale_assistente")).content.decode()
    assert "Ho fatture da pagare?" in pagina and "la FT/1." in pagina and "visibili al nostro staff" in pagina


def test_la_domanda_prima_fa_da_contesto(client, scena, modello):
    client.force_login(scena["accesso"].utente)
    client.post(reverse("discuss:portale_assistente"), {"domanda": "Come funzionano i resi?"})
    client.post(reverse("discuss:portale_assistente"), {"domanda": "E entro quanto?"})
    assert "Cliente: Come funzionano i resi?" in modello["chiamate"][1]["testo"]


def test_quando_non_sa_propone_una_richiesta(client, scena, modello):
    modello["risposta"] = MARCATORE
    client.force_login(scena["accesso"].utente)
    client.post(reverse("discuss:portale_assistente"), {"domanda": "Mi fate uno sconto del 20%?"})
    voce = DomandaPortale.objects.get()
    assert voce.senza_risposta and "Apri una richiesta" in voce.risposta
    assert DomandaSenzaRisposta.objects.filter(sportello=scena["sportello"], testo__contains="sconto").exists()
    assert reverse("assistenza:portale_nuovo") in client.get(reverse("discuss:portale_assistente")).content.decode()


def test_modello_giu_e_tetto_del_giorno(client, scena, modello, monkeypatch):
    modello["risposta"] = RuntimeError("provider giù")
    voce = portale_assistente.rispondi(scena["accesso"], "Orari?")
    assert voce.senza_risposta and voce.risposta
    monkeypatch.setattr(portale_assistente, "DOMANDE_AL_GIORNO", 1)
    modello["risposta"] = "ok"
    voce = portale_assistente.rispondi(scena["accesso"], "Altro?")
    assert "molte domande" in voce.risposta and len(modello["chiamate"]) == 1


def test_solo_per_i_clienti_e_lo_staff_vede_le_domande(client, scena, modello):
    client.force_login(scena["interno"])
    assert client.get(reverse("discuss:portale_assistente")).status_code == 403          # un utente interno non è un cliente
    portale_assistente.rispondi(scena["accesso"], "Come faccio un reso?")
    scena["interno"].profilo.aziende.set([scena["azienda"]])
    scena["interno"].profilo.azienda_predefinita = scena["azienda"]
    scena["interno"].profilo.save()
    assert "Come faccio un reso?" in client.get("/discuss/domande_portale/").content.decode()


def test_gli_articoli_pubblicati_della_guida_entrano_nelle_informazioni(client, scena, modello):
    from helpdesk.models import Articolo
    Articolo.objects.create(azienda=scena["azienda"], titolo="Cambio password", corpo="Per cambiare la password usa Profilo.", pubblicato=True)
    Articolo.objects.create(azienda=scena["azienda"], titolo="Password interna", corpo="La password del server è x.", pubblicato=False)
    portale_assistente.rispondi(scena["accesso"], "come cambio la password?")
    sistema = modello["chiamate"][0]["sistema"]
    assert "usa Profilo" in sistema and "server" not in sistema
