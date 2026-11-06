"""App predefinita di un progetto: le chat nuove partono limitate a quell'app, che dalla casella si toglie o si cambia."""
from django.urls import reverse

from ai import pagine
from ai.models import Conversazione, ProgettoChat
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)

import pytest

FINTE = [{"slug": "crm", "label": "CRM", "icon": "crm/icon.svg", "url": "/crm/", "category": "Vendite"},
         {"slug": "todo", "label": "To-Do", "icon": "todo/icon.svg", "url": "/todo/", "category": ""}]


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(pagine, "app_selezionabili", lambda user: FINTE)


def test_form_e_chat_nuova_nel_progetto(client, s, app, settings):
    settings.AI_TURNI_SINCRONI = True
    p = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Ricerche prodotti")
    form = client.get(reverse("ai:progetti_modifica", args=[p.pk])).content.decode()
    assert '<option value="crm">CRM</option>' in form and "Tutte le app" in form
    client.post(reverse("ai:progetti_modifica", args=[p.pk]), {"nome": "Ricerche prodotti", "istruzioni": "", "ambito": "crm"})
    p.refresh_from_db()
    assert p.ambito == "crm"
    pagina = client.get(reverse("ai:progetto", args=[p.pk])).content.decode()
    assert 'name="ambito" value="crm" data-ambito' in pagina and "App predefinita" in pagina
    client.post(reverse("ai:invia"), {"testo": "prima", "progetto": p.pk, "ambito": "crm"})
    client.post(reverse("ai:invia"), {"testo": "seconda", "progetto": p.pk, "ambito": ""})        # tolta dalla casella
    assert Conversazione.objects.get(messaggi__testo="prima").ambito == "crm"
    assert Conversazione.objects.get(messaggi__testo="seconda").ambito == ""


def test_app_non_piu_visibile(client, s, app, monkeypatch):
    p = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Vecchio", ambito="magazzino")
    pagina = client.get(reverse("ai:progetto", args=[p.pk])).content.decode()
    assert 'name="ambito" value="" data-ambito' in pagina                              # niente app che l'utente non vede
    assert "non più disponibile" in client.get(reverse("ai:progetti_modifica", args=[p.pk])).content.decode()


def test_conversazione_esistente_tiene_la_sua_app(client, s, app):
    p = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="X", ambito="crm")
    c = Conversazione.objects.create(utente=s["u"], titolo="x", progetto=p, ambito="todo")
    assert 'name="ambito" value="todo" data-ambito' in client.get(reverse("ai:conversazione", args=[c.pk])).content.decode()
