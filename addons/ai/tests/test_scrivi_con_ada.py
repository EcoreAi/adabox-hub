"""«Scrivi con Ada»: bozza dalle risposte o miglioramento del testo, solo letture del gestionale, chat nascosta."""
import json

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from ai import aiuto_testi
from ai.gateway import finto
from ai.models import Conversazione, Turno
from ai.strumenti import disponibili
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)


@pytest.fixture
def sincrono(settings):
    settings.AI_TURNI_SINCRONI = True


def test_richiesta_intervista_e_miglioramento():
    regole, corpo = aiuto_testi.richiesta("progetto", "", {"0": "Sviluppo di AdaV3", "2": "brevi"})
    assert "controllalo con gli strumenti" in regole and aiuto_testi.SEPARATORE_NOTE in regole
    assert "Sviluppo di AdaV3" in corpo and "(nessuna risposta)" in corpo and "Su cosa lavori" in corpo
    _, corpo = aiuto_testi.richiesta("pianificata", "Ogni mattina guarda i ticket", {})
    assert corpo.startswith("Migliora") and "Ogni mattina guarda i ticket" in corpo
    assert "senza nessuno a cui chiedere" in aiuto_testi.richiesta("pianificata", "", {})[0]


def test_solo_letture_del_gestionale(s):
    ammessi = aiuto_testi.filtra_strumenti({x.nome: x for x in disponibili(s["u"])})
    assert ammessi and all(x.rischio == "lettura" for x in ammessi.values())
    assert not aiuto_testi.ESCLUSI & set(ammessi) and not any(n.startswith("mcp") for n in ammessi)


def test_bozza_con_note(client, s, sincrono):
    risposta = ["Lavoriamo su AdaV3.\n\nCome rispondere\n- breve\n\nNOTE:\nNon ho trovato la commessa «AdaV3»."]
    with finto.con_copione([risposta]) as chiamate:
        r = client.post(reverse("ai:scrivi_con_ada", args=["progetto"]), {"risposte": json.dumps({"0": "AdaV3"})})
    esito = client.get(r.json()["esito"]).json()
    assert esito == {"bozza": "Lavoriamo su AdaV3.\n\nCome rispondere\n- breve", "note": "Non ho trovato la commessa «AdaV3»."}
    offerti = set(chiamate[0]["strumenti"])
    assert offerti and not offerti & {"crea_record", "modifica_record", "scrivi_documento", "cerca_web", "ricorda"}
    t = Turno.objects.get(compito="aiuto")
    assert t.azienda == s["az"] and t.conversazione.nascosta and t.web is False                   # costi nel tetto dell'azienda
    assert "Scrivi con Ada" not in client.get(reverse("ai:chat")).content.decode().split('id="ai-elenco-storico"')[1][:3000]


def test_permessi_e_turni_altrui(client, s, sincrono):
    s["u"].user_permissions.remove(Permission.objects.get(codename="add_pianificata"))
    client.force_login(User.objects.get(pk=s["u"].pk))
    assert client.post(reverse("ai:scrivi_con_ada", args=["pianificata"]), {}).status_code == 403
    assert client.post(reverse("ai:scrivi_con_ada", args=["sconosciuto"]), {}).status_code == 404
    with finto.con_copione([["Testo"]]):
        url = client.post(reverse("ai:scrivi_con_ada", args=["progetto"]), {"testo": "vecchio"}).json()["esito"]
    altro = User.objects.create_user("bruno", password="x")
    altro.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    client.force_login(altro)
    assert client.get(url).status_code == 404


def test_pulsante_nei_tre_form(client, s):
    for nome in ("ai:progetti_nuovo", "ai:pianificate_nuovo", "ai:assistenti_nuovo"):
        pagina = client.get(reverse(nome)).content.decode()
        assert "data-scrivi-con-ada" in pagina and 'id="ai-scrivi"' in pagina and "scrivi_con_ada.js" in pagina, nome


def test_esito_in_corso_e_errore(s):
    c = Conversazione.objects.create(utente=s["u"], titolo="x", nascosta=True)
    t = Turno.objects.create(conversazione=c, utente=s["u"], compito="aiuto")
    assert aiuto_testi.esito(t) is None
    t.stato = Turno.ERRORE
    assert "errore" in aiuto_testi.esito(t)
