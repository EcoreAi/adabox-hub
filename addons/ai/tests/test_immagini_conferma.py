"""Immagini verso i modelli cloud: mai, con la conferma dell'utente (registrata) o sempre; con un modello locale che
le legge non escono e non serve conferma."""
import importlib
from decimal import Decimal

import pytest
from django.apps import apps as registro_app
from django.urls import reverse

from ai import allegati_chat
from ai.allegati_chat import ImmagineDaConfermare
from ai.gateway import esecuzione
from ai.models import AnelloCatena, Conversazione, Evento, MessaggioChat, Modello, Profilo, Provider
from ai.motore import turni
from ai.tests.test_chat_gruppo2 import PNG, s  # noqa: F401  (fixture)
from core.allegati import AllegatoNonValido
from core.models import Parametro
from django.core.files.uploadedfile import SimpleUploadedFile


def _png():
    return SimpleUploadedFile("foto.png", PNG)


@pytest.fixture
def cloud(s, monkeypatch, settings):
    """La catena della chat diventa un modello cloud che legge le immagini; azienda in «conferma»."""
    settings.AI_TURNI_SINCRONI = True
    fornitore = Provider.objects.create(nome="Cloud", tipo="finto", locale=False)
    m = Modello.objects.create(provider=fornitore, id_api="cloud-1", etichetta="Cloud Vision", visione=True, prezzo_input=Decimal(1), prezzo_output=Decimal(1))
    AnelloCatena.objects.filter(profilo__compito="chat").delete()
    AnelloCatena.objects.create(profilo=Profilo.objects.get(compito="chat"), modello=m, ordine=1)
    Modello.objects.filter(pk=s["modello"].pk).update(visione=False)                   # il modello locale del fixture non vede
    modo = {"v": "conferma"}
    monkeypatch.setattr(allegati_chat, "modo_immagini", lambda azienda: modo["v"])
    visti = []

    def adattatore(modello, chiave, **richiesta):
        if any(m.get("immagini_dati") for m in richiesta["messaggi"]):          # non il turno dei titoli
            visti.append(modello.id_api)
        from ai.gateway.tipi import Fine, Testo
        yield Testo("Vedo una foto")
        yield Fine("fine", [{"tipo": "testo", "testo": "Vedo una foto"}])
    monkeypatch.setitem(esecuzione.ADATTATORI, "finto", adattatore)
    return {"modello": m, "modo": modo, "visti": visti}


def test_le_tre_scelte(s, cloud):
    with pytest.raises(ImmagineDaConfermare, match="conferma l'invio"):
        allegati_chat.controlla([_png()], s["az"])
    allegati_chat.controlla([_png()], s["az"], confermate=True)
    cloud["modo"]["v"] = "mai"
    with pytest.raises(AllegatoNonValido, match="amministratore") as e:
        allegati_chat.controlla([_png()], s["az"], confermate=True)
    assert not isinstance(e.value, ImmagineDaConfermare)
    cloud["modo"]["v"] = "sempre"
    allegati_chat.controlla([_png()], s["az"])


def test_con_conferma_arriva_al_cloud_e_resta_scritto(client, s, cloud):
    r = client.post(reverse("ai:invia"), {"testo": "cosa vedi", "allegati": [_png()]})
    assert not Conversazione.objects.exists() and r.status_code in (200, 302)              # senza conferma niente chat
    client.post(reverse("ai:invia"), {"testo": "cosa vedi", "allegati": [_png()], "conferma_immagini": "1"})
    c = Conversazione.objects.get()
    conferma = c.eventi.get(tipo=Evento.UTENTE).dati["immagini_confermate"]
    assert conferma["utente"] == s["u"].username and conferma["quando"] and cloud["visti"] == ["cloud-1"]
    domanda = c.messaggi.get(ruolo=MessaggioChat.UTENTE)                                    # rigenerare tiene la conferma
    turni.riparti(c, domanda, domanda.testo, s["u"], s["az"])
    assert cloud["visti"] == ["cloud-1", "cloud-1"]


def test_con_un_modello_locale_l_immagine_la_descrive_lui_e_la_chat_continua(client, s, cloud):
    Modello.objects.filter(pk=s["modello"].pk).update(visione=True)                         # locale, non nella catena della chat
    assert not allegati_chat.serve_conferma(s["az"])
    client.post(reverse("ai:invia"), {"testo": "cosa vedi", "allegati": [_png()]})
    c = Conversazione.objects.get()
    dati = c.eventi.get(tipo=Evento.UTENTE).dati
    assert "immagini_confermate" not in dati and cloud["visti"] == [s["modello"].id_api]       # l'immagine solo al locale
    assert "immagini" not in dati and dati["immagini_descritte"] and "Vedo una foto" in dati["testo"] and "<immagini_allegate" in dati["testo"]
    assert c.turni.get(compito="chat").modello == cloud["modello"]                      # la chat continua col suo modello
    assert c.messaggi.filter(ruolo="assistente").exists()


def test_riquadro_nella_casella_solo_quando_serve(client, s, cloud):
    pagina = client.get(reverse("ai:chat")).content.decode()
    assert "data-conferma-box" in pagina and "Cloud Vision" in pagina
    cloud["modo"]["v"] = "sempre"
    assert "data-conferma-box" not in client.get(reverse("ai:chat")).content.decode()


def test_valori_vecchi_e_migrazione(s):
    Parametro.objects.create(chiave="ai.immagini_cloud", azienda=s["az"], valore=True)
    Parametro.objects.create(chiave="ai.immagini_cloud", azienda=s["altra"], valore=False)
    migrazione = importlib.import_module("ai.migrations.0020_immagini_cloud_tre_scelte")
    migrazione.avanti(registro_app, None)
    assert dict(Parametro.objects.filter(chiave="ai.immagini_cloud").values_list("azienda", "valore")) == {s["az"].pk: "sempre", s["altra"].pk: "conferma"}
    assert allegati_chat.modo_immagini(s["az"]) == "sempre" and allegati_chat.modo_immagini(s["altra"]) == "conferma"
