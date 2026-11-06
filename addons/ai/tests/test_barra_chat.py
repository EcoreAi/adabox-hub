"""La barra del campo della chat: ricerca sul web scelta messaggio per messaggio, livelli del modello, scheda delle app."""
from decimal import Decimal

from django.urls import reverse

from ai import pagine
from ai.gateway import finto
from ai.models import Conversazione, MessaggioChat, Modello, Turno
from ai.motore import turni
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)
from ai.tests.test_ricerca import web_acceso  # noqa: F401  (fixture)


def _strumenti_offerti(chiamate):
    return set(chiamate[0]["strumenti"])


def test_senza_scelta_niente_web_anche_se_l_azienda_lo_ha_acceso(client, s, web_acceso):  # noqa: F811
    with finto.con_copione([["ok"]]) as chiamate:
        client.post(reverse("ai:invia"), {"testo": "domanda", "ricerca": ""})
    t = Turno.objects.get(compito="chat")
    assert t.web is False and not {"cerca_web", "leggi_pagina"} & _strumenti_offerti(chiamate)


def test_ricerca_sul_web_per_un_messaggio(client, s, web_acceso):  # noqa: F811
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    with finto.con_copione([["ok"]]) as chiamate:
        client.post(reverse("ai:invia_conversazione", args=[c.pk]), {"testo": "novità IVA?", "ricerca": "web"})
    t = c.turni.get(compito="chat")
    assert t.web and {"cerca_web", "leggi_pagina"} <= _strumenti_offerti(chiamate)
    assert "ricerca sul web" in str(chiamate[0]["messaggi"])
    domanda = c.messaggi.get(ruolo=MessaggioChat.UTENTE)
    with finto.con_copione([["di nuovo"]]) as chiamate:                     # rigenerare tiene la scelta
        turni.riparti(c, domanda, domanda.testo, s["u"], s["az"])
    assert {"cerca_web"} <= _strumenti_offerti(chiamate)


def test_approfondita_e_web_spento_per_l_azienda(client, s, web_acceso):  # noqa: F811
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    with finto.con_copione([["ok"]]):
        client.post(reverse("ai:invia_conversazione", args=[c.pk]), {"testo": "studia", "ricerca": "approfondita"})
    assert c.turni.filter(compito="ricerca", web=True).exists()
    web_acceso["ai.ricerca_web"] = False
    with finto.con_copione([["ok"]]) as chiamate:
        client.post(reverse("ai:invia_conversazione", args=[c.pk]), {"testo": "e ora?", "ricerca": "web"})
    assert c.turni.order_by("-pk").first().web is False and "cerca_web" not in _strumenti_offerti(chiamate)


def test_le_pianificate_e_gli_altri_turni_tengono_il_web(s):
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    assert Turno.objects.create(conversazione=c, utente=s["u"]).web is True


def test_livelli_del_modello(client, s):
    assert pagine.livelli_modello(s["az"]) == []
    medio = Modello.objects.create(provider=s["provider"], id_api="m", etichetta="Medio", sceglibile=True, prezzo_input=Decimal(3), prezzo_output=Decimal(15))
    assert pagine.livelli_modello(s["az"]) == [("standard", medio)]
    economico = Modello.objects.create(provider=s["provider"], id_api="e", etichetta="Economico", sceglibile=True, prezzo_input=Decimal(1), prezzo_output=Decimal(5))
    capace = Modello.objects.create(provider=s["provider"], id_api="c", etichetta="Capace", sceglibile=True, prezzo_input=Decimal(5), prezzo_output=Decimal(25))
    assert pagine.livelli_modello(s["az"]) == [("standard", economico), ("max", capace)]
    c = Conversazione.objects.create(utente=s["u"], titolo="x", modello=capace)
    pagina = client.get(reverse("ai:conversazione", args=[c.pk])).content.decode()
    assert "Standard" in pagina and "Economico" in pagina and "Max" in pagina and "Capace" in pagina and "Medio" not in pagina
    assert f'name="modello" value="{capace.pk}"' in pagina


def test_scheda_delle_app_in_colonne(client, s):
    from django.contrib.auth.models import Permission
    s["u"].user_permissions.set(Permission.objects.all())
    pagina = client.get(reverse("ai:chat")).content.decode()
    assert "ai-scheda-colonna" in pagina and "ai-scheda-titolo" in pagina and 'data-ambito-app=""' in pagina
    assert "Risposta vocale" not in pagina.split('class="ai-composer-barra"')[1].split("</form>")[0].replace('aria-label="Risposta vocale"', "")
