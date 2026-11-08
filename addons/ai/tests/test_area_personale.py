"""Aree di lavoro: ognuno ha sempre la sua area personale (privata, non si elimina); ogni chat sta in un'area; l'area
corrente decide dove nascono le chat nuove e si cambia dalla tendina o aprendo un'area; le chat orfane tornano a casa."""
import importlib

import pytest
from django.urls import reverse

from ai import aree
from ai.models import AreaCorrente, Conversazione, ProgettoChat
from ai.tests.test_chat_gruppo2 import _utente, s  # noqa: F401  (fixture)


def test_area_personale_sempre_presente_e_privata(client, s):
    assert not ProgettoChat.objects.filter(personale=True).exists()
    html = client.get(reverse("ai:chat")).content.decode()
    mia = ProgettoChat.objects.get(utente=s["u"], personale=True)
    assert mia.nome == "Il mio spazio" and "ai-barra-area" in html and "Il mio spazio · personale" in html
    assert aree.corrente(s["u"], s["az"]) == mia
    bruno = _utente("bruno", s["az"])
    aree.imposta_membri(mia, [bruno])
    assert not mia.membri.exists()                                              # non si condivide
    form = client.get(f"/ai/progetti/{mia.pk}/modifica/").content.decode()
    assert 'name="membri"' not in form
    assert client.post(f"/ai/progetti/{mia.pk}/elimina/").status_code in (302, 403)
    assert ProgettoChat.objects.filter(pk=mia.pk).exists()                     # non si elimina


def test_la_chat_nuova_nasce_nell_area_corrente(client, s):
    client.post(reverse("ai:invia"), {"testo": "ciao"})
    c = Conversazione.objects.get()
    assert c.progetto == aree.personale(s["u"], s["az"])
    lavoro = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Sito Rossi")
    client.get(reverse("ai:progetto", args=[lavoro.pk]))                         # aprire un'area è lavorarci
    assert aree.corrente(s["u"], s["az"]) == lavoro
    client.get(reverse("ai:chat"))
    client.post(reverse("ai:invia"), {"testo": "secondo"})
    assert Conversazione.objects.order_by("-pk").first().progetto == lavoro
    client.post(reverse("ai:area_corrente"), {"area": aree.personale(s["u"], s["az"]).pk, "da": "/ai/chat/"})
    assert aree.corrente(s["u"], s["az"]).personale


def test_spostare_una_chat(client, s):
    lavoro = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Sito Rossi")
    c = Conversazione.objects.create(utente=s["u"], titolo="x", progetto=aree.personale(s["u"], s["az"]))
    client.post(reverse("ai:sposta", args=[c.pk]), {"progetto": lavoro.pk})
    c.refresh_from_db()
    assert c.progetto == lavoro and aree.corrente(s["u"], s["az"]) == lavoro
    client.post(reverse("ai:sposta", args=[c.pk]), {"progetto": ""})            # mai fuori da un'area
    c.refresh_from_db()
    assert c.progetto.personale
    altra = ProgettoChat.objects.create(utente=_utente("zeno", s["altra"]), azienda=s["altra"], nome="Non mia")
    client.post(reverse("ai:sposta", args=[c.pk]), {"progetto": altra.pk})
    c.refresh_from_db()
    assert c.progetto.personale


def test_chi_esce_e_area_eliminata_riportano_le_chat_a_casa(s):
    bruno = _utente("bruno", s["az"])
    condivisa = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Team")
    aree.imposta_membri(condivisa, [bruno])
    sua = Conversazione.objects.create(utente=bruno, titolo="di Bruno", progetto=condivisa, condivisa=True)
    mia = Conversazione.objects.create(utente=s["u"], titolo="di Anna", progetto=condivisa)
    aree.imposta_membri(condivisa, [])
    sua.refresh_from_db()
    assert sua.progetto == aree.personale(bruno, s["az"]) and not sua.condivisa
    condivisa.delete()
    mia.refresh_from_db()
    assert mia.progetto == aree.personale(s["u"], s["az"])


def test_area_corrente_non_piu_visibile(s):
    bruno = _utente("bruno", s["az"])
    sua = ProgettoChat.objects.create(utente=bruno, azienda=s["az"], nome="Di Bruno")
    aree.imposta_membri(sua, [s["u"]])
    aree.imposta_corrente(s["u"], sua)
    assert aree.corrente(s["u"], s["az"]) == sua
    aree.imposta_membri(sua, [])
    assert aree.corrente(s["u"], s["az"]).personale and AreaCorrente.objects.filter(utente=s["u"]).exists()


def test_migrazione_delle_chat_senza_area(s):
    from django.apps import apps as registro
    Conversazione.objects.create(utente=s["u"], titolo="vecchia")
    Conversazione.objects.create(utente=s["u"], titolo="interna", nascosta=True)
    mig = importlib.import_module("ai.migrations.0032_area_personale")
    mig.area_personale_a_tutti(registro, None)
    assert Conversazione.objects.get(titolo="vecchia").progetto.personale
    assert Conversazione.objects.get(titolo="interna").progetto is None              # le interne restano com'erano
