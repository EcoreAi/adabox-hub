"""CRM-19: il modulo «contattaci» del sito crea un'opportunità con origine, etichetta, contatto e attività al
commerciale; solo dai siti ammessi, con esca e limite; dalla chat del sito il lead parte con nome ed email."""
import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.urls import reverse

from contatti.models import Contatto
from core.models import AttivitaPianificata, Azienda, TipoAttivita
from crm import modulo_web
from crm.models import EtichettaCrm, ModuloWeb, Opportunita

SITO = "https://www.miosito.it"


@pytest.fixture
def modulo(db):
    from pathlib import Path

    from django.core.management import call_command

    import crm
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    cache.clear()
    TipoAttivita.objects.get_or_create(nome="Chiamata")
    az = Azienda.objects.get(pk=1)
    marco = User.objects.create_user("marco", "marco@example.com", "x")
    return ModuloWeb.objects.create(azienda=az, nome="Contatti", domini=f"{SITO}/\nhttps://altro.it", commerciale=marco,
                                    etichetta=EtichettaCrm.objects.create(nome="Sito web"))


def _invia(client, modulo, origine=SITO, **dati):
    return client.post(reverse("crm:modulo_web", args=[modulo.chiave]),
                       {"nome": "Giulia Bianchi", "email": "giulia@bianchi.it", **dati}, HTTP_ORIGIN=origine)


def test_dal_modulo_all_opportunita(client, modulo):
    gia = Contatto.objects.create(azienda=modulo.azienda, nome="Giulia Bianchi", email="Giulia@Bianchi.it")
    r = _invia(client, modulo, telefono="333 1234567", azienda="Bianchi Srl", messaggio="Vorrei un preventivo",
               pagina=f"{SITO}/servizi", utm_source="google")
    assert r.status_code == 200 and r.json()["ok"] and r["Access-Control-Allow-Origin"] == SITO
    o = Opportunita.objects.get()
    assert o.titolo == "Giulia Bianchi · Bianchi Srl" and o.contatto == gia and o.commerciale == modulo.commerciale
    assert o.origine == "Modulo del sito: Contatti" and list(o.etichette.all()) == [modulo.etichetta]
    assert "Vorrei un preventivo" in o.note and "utm_source: google" in o.note and o.telefono == "333 1234567"
    a = AttivitaPianificata.objects.get()
    assert a.assegnatario == modulo.commerciale and "Ricontattare Giulia Bianchi" in a.riepilogo


def test_controlli(client, modulo):
    assert _invia(client, modulo, origine="https://intruso.it").status_code == 403
    assert _invia(client, modulo, email="non-email").status_code == 400
    assert _invia(client, modulo, sito_web="http://spam").json()["ok"] and not Opportunita.objects.exists()   # esca
    for _ in range(modulo_web.LIMITE_ORA):
        assert _invia(client, modulo).status_code == 200
    assert _invia(client, modulo).status_code == 429
    modulo.domini = ""
    modulo.save()
    assert _invia(client, modulo).status_code == 404                     # senza siti ammessi è spento
    opzioni = client.options(reverse("crm:modulo_web", args=[modulo.chiave]), HTTP_ORIGIN=SITO)
    assert opzioni.status_code == 404


def test_codice_da_incollare(client, superuser, modulo):
    html = client.get(f"/crm/moduli/{modulo.pk}/").content.decode()
    assert "data-adabox-lead=" in html and modulo.chiave in html and "crm/modulo-web.js" in html


def test_dalla_chat_del_sito_con_nome_ed_email(db, superuser):
    from django.apps import apps
    if not apps.is_installed("discuss"):
        pytest.skip("Discuss non installato")
    from django.test import RequestFactory

    from core.viste import registry
    from discuss import schede
    from discuss.models import Canale, ConversazioneEsterna, Messaggio, Sportello
    sportello = Sportello.objects.create(nome="Sito")
    canale = Canale.objects.create(nome="Visitatore", tipo=Canale.objects.model._meta.get_field("tipo").choices[0][0])
    ConversazioneEsterna.objects.create(sportello=sportello, canale=canale, token="t", nome="Paolo Neri", email="paolo@neri.it", impronta_ip="x")
    m = Messaggio.objects.create(canale=canale, corpo="Mi serve un preventivo", autore_esterno="Paolo Neri")
    request = RequestFactory().get("/")
    request.user, request.azienda = superuser, Azienda.objects.get(pk=1)
    valori = schede.iniziali(registry.per_modello(Opportunita), request, m)
    assert valori["nome_contatto"] == "Paolo Neri" and valori["email"] == "paolo@neri.it"
