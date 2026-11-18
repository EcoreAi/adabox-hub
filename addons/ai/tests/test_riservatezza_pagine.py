"""Chat riservate nell'interfaccia: segnarle, vederlo in chat e nella provenienza (piano 2026-11-18)."""
import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from ai import provenienza
from ai.models import Conversazione, Turno
from core.models import Azienda

ETICHETTA = "Riservata · solo modelli locali"


@pytest.fixture
def capo(db, client):
    u = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(u)
    return u


def test_rendi_riservata(client, capo):
    c = Conversazione.objects.create(utente=capo)
    url = reverse("ai:riservata", args=[c.pk])
    assert client.get(url).status_code == 405
    assert client.post(url).status_code == 302
    c.refresh_from_db()
    assert c.riservata and c.riservata_motivo == "segnata dall'utente"
    altrui = Conversazione.objects.create(utente=User.objects.create_user("altro"))
    assert client.post(reverse("ai:riservata", args=[altrui.pk])).status_code == 404


def test_etichetta_in_chat(client, capo):
    c = Conversazione.objects.create(utente=capo)
    pagina = client.get(reverse("ai:conversazione", args=[c.pk])).content.decode()
    assert ETICHETTA not in pagina and reverse("ai:riservata", args=[c.pk]) in pagina
    Conversazione.objects.filter(pk=c.pk).update(riservata=True, riservata_motivo="app «personale»")
    pagina = client.get(reverse("ai:conversazione", args=[c.pk])).content.decode()
    assert ETICHETTA in pagina and "app «personale»" in pagina
    assert reverse("ai:riservata", args=[c.pk]) not in pagina


def test_provenienza_riservata(capo):
    c = Conversazione.objects.create(utente=capo, riservata=True, riservata_motivo="x")
    turno = Turno.objects.create(conversazione=c, utente=capo, azienda=Azienda.objects.get(pk=1))
    pv = provenienza.calcola(turno, "Ecco.")
    assert pv["riservata"] is True
    from django.template.loader import render_to_string
    assert ETICHETTA in render_to_string("ai/_provenienza.html", {"pv": pv})
    normale = Turno.objects.create(conversazione=Conversazione.objects.create(utente=capo), utente=capo)
    assert provenienza.calcola(normale, "Ecco.").get("riservata") is False
