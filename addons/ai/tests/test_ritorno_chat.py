"""I link delle proposte di Ada si aprono nella stessa finestra e la pagina aperta ha «← Torna alla chat»;
durante la risposta il pulsante d'invio diventa «Ferma»."""
import pytest
from django.contrib.auth.models import User
from django.template.loader import render_to_string

from ai.models import Conversazione, Proposta
from ai.templatetags.ai import con_ritorno


@pytest.fixture
def capo(db, client):
    u = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(u)
    return u


def _proposta(capo, url):
    c = Conversazione.objects.create(utente=capo, titolo="Prova")
    return Proposta.objects.create(conversazione=c, utente=capo, strumento="analisi_crea_dashboard", titolo="Crea",
                                   stato=Proposta.ESEGUITA, url=url, esito="Fatto.")


def test_link_della_proposta_nella_stessa_finestra(capo):
    p = _proposta(capo, "/grafici/pagina/3/")
    html = render_to_string("ai/_proposta.html", {"p": p})
    assert f'href="/grafici/pagina/3/?da_chat={p.conversazione_id}"' in html
    assert 'target="_blank"' not in html


def test_con_ritorno_tiene_la_query():
    assert con_ritorno("/vendite/ordini/?f_stato=aperto", 7) == "/vendite/ordini/?f_stato=aperto&da_chat=7"
    assert con_ritorno("/x/#parte", 7) == "/x/?da_chat=7#parte"
    assert con_ritorno("https://esterno.example/", 7) == "https://esterno.example/"   # fuori dal gestionale: com'è
    assert con_ritorno("", 7) == ""


def test_la_pagina_aperta_ha_torna_alla_chat(capo, client):
    c = Conversazione.objects.create(utente=capo, titolo="Prova")
    html = client.get(f"/grafici/?da_chat={c.pk}").content.decode()
    assert f'href="/ai/chat/{c.pk}/"' in html and "Torna alla chat" in html
    assert "Torna alla chat" not in client.get("/grafici/?da_chat=abc").content.decode()
    assert "Torna alla chat" not in client.get("/grafici/").content.decode()


def test_torna_solo_alle_proprie_chat(capo, client):
    altro = User.objects.create_user("altro", "a@example.com", "x")
    c = Conversazione.objects.create(utente=altro, titolo="Sua")
    assert "Torna alla chat" not in client.get(f"/grafici/?da_chat={c.pk}").content.decode()


def test_ferma_nel_composer_non_nella_bolla(capo, client):
    from django.utils import timezone

    from ai.models import MessaggioChat, Turno
    c = Conversazione.objects.create(utente=capo, titolo="Prova")
    MessaggioChat.objects.create(conversazione=c, ruolo="utente", testo="ciao")
    Turno.objects.create(conversazione=c, utente=capo, stato="in_corso", compito="chat", battito=timezone.now())
    html = client.get(f"/ai/chat/{c.pk}/").content.decode()
    assert "data-flusso" in html                                          # la risposta in corso c'è
    assert "data-ferma-composer" in html and "data-ferma>" not in html and 'class="ai-stop"' not in html
