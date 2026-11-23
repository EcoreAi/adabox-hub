"""Tema per azienda: tema, nome del prodotto e template dell'azienda corrente o del documento (pagine pubbliche)."""
import types

import pytest
from django.core.exceptions import ValidationError
from django.template import engines
from django.urls import reverse

import theme
from core import azienda as az
from core import modelli_email
from core.models import Azienda
from theme import template_tema
from theme.context_processors import SESSIONE_ANTEPRIMA
from theme.models import Tema

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def cache_pulita():
    """Il loader dei template del tema ha una cache per (pacchetto, nome) che vive con il motore dei template."""
    def pulisci():
        for loader in engines["django"].engine.template_loaders:
            if hasattr(loader, "reset"):
                loader.reset()
    pulisci()
    yield
    pulisci()


@pytest.fixture
def due_aziende(superuser, client):
    zen = Azienda.objects.get(pk=1)
    iem = Azienda.objects.create(nome="IEM Srl")
    tema = Tema.objects.create(nome="IEM", marchio="IEM Hub", colore_barra="#aa3300", css=":root{--ui-primary:#a30}")
    iem.tema = tema
    iem.save()
    from core.models import ProfiloUtente
    profilo, _ = ProfiloUtente.objects.get_or_create(utente=superuser)
    profilo.aziende.add(zen, iem)
    return types.SimpleNamespace(zen=zen, iem=iem, tema=tema, client=client)


def _scegli(client, azienda):
    sessione = client.session
    sessione[az.CHIAVE_SESSIONE] = azienda.pk
    sessione.save()


def _pagina(client):
    return client.get(reverse("core:profilo")).content.decode()


def test_il_tema_segue_l_azienda_corrente(due_aziende):
    c = due_aziende.client
    _scegli(c, due_aziende.zen)
    html = _pagina(c)
    assert "IEM Hub" not in html and "#aa3300" not in html
    _scegli(c, due_aziende.iem)
    html = _pagina(c)
    assert "· IEM Hub</title>" in html and 'content="#aa3300"' in html
    assert reverse("theme:tema_css", args=[due_aziende.tema.pk]) in html               # il CSS del tema
    assert f"?t={due_aziende.tema.pk}." in html                     # la favicon di quel tema


def test_i_template_del_tema_vengono_prima_solo_per_quell_azienda(due_aziende, tmp_path, monkeypatch, settings):
    cartella = tmp_path / "templates" / "theme" / "partials"
    cartella.mkdir(parents=True)
    (cartella / "_logo.html").write_text("<span>LOGO-IEM</span>")
    monkeypatch.setattr(template_tema, "cartella", lambda p: tmp_path / "templates" if p == "iem.tema" else None)
    Tema.objects.filter(pk=due_aziende.tema.pk).update(template="iem.tema")
    settings.DEBUG = False                                           # con la cache dei template accesa
    c = due_aziende.client
    _scegli(c, due_aziende.iem)
    assert "LOGO-IEM" in _pagina(c)
    _scegli(c, due_aziende.zen)
    html = _pagina(c)
    assert "LOGO-IEM" not in html and "ui-logo-cubo" in html
    _scegli(c, due_aziende.iem)
    assert "LOGO-IEM" in _pagina(c)


def test_template_del_tema_solo_da_un_modulo_attivo(settings):
    for sbagliato in ("os", "core.templates", "../etc", "modulo_inesistente.tema"):
        with pytest.raises(ValidationError):
            Tema(nome="X", template=sbagliato).full_clean()
    attivo = next((s for s in settings.ADDONS_ATTIVI if template_tema.cartella(s)), None)
    if attivo:
        Tema(nome="Y", template=attivo).full_clean()


def test_senza_tema_dell_azienda_vale_quello_attivo(due_aziende):
    attivo = Tema.objects.get(attivo=True)
    Tema.objects.filter(pk=attivo.pk).update(marchio="Hub del gruppo")
    _scegli(due_aziende.client, due_aziende.zen)
    assert "· Hub del gruppo</title>" in _pagina(due_aziende.client)


def test_l_anteprima_dello_staff_vince(due_aziende):
    altro = Tema.objects.create(nome="Prova", marchio="In prova")
    c = due_aziende.client
    _scegli(c, due_aziende.iem)
    sessione = c.session
    sessione[SESSIONE_ANTEPRIMA] = altro.pk
    sessione.save()
    html = _pagina(c)
    assert "· In prova</title>" in html and "IEM Hub" not in html


def test_favicon_del_tema_qualunque_sia_la_sessione(due_aziende, tmp_path, monkeypatch):
    c = due_aziende.client
    _scegli(c, due_aziende.zen)
    cartella = tmp_path / "templates" / "theme" / "partials"
    cartella.mkdir(parents=True)
    (cartella / "_favicon.svg").write_text('<svg class="ui-logo-cubo" viewBox="0 0 1 1"><title>IEM</title></svg>')
    monkeypatch.setattr(template_tema, "cartella", lambda p: tmp_path / "templates" if p == "iem.tema" else None)
    Tema.objects.filter(pk=due_aziende.tema.pk).update(template="iem.tema")
    r = c.get(reverse("theme:favicon"), {"t": f"{due_aziende.tema.pk}.1"})
    assert "<title>IEM</title>" in r.content.decode() and r["Content-Type"] == "image/svg+xml"
    assert "<title>IEM</title>" not in c.get(reverse("theme:favicon")).content.decode()
    Tema.objects.filter(pk=due_aziende.tema.pk).update(logo=b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                                                      logo_tipo="image/svg+xml")
    r = c.get(reverse("theme:favicon"), {"t": f"{due_aziende.tema.pk}.2"})
    assert r.status_code == 302 and reverse("theme:tema_logo", args=[due_aziende.tema.pk]) in r["Location"]


def test_marchio_nelle_email_dell_azienda(due_aziende, settings):
    settings.THEME = {**settings.THEME, "brand": "Hub"}
    assert theme.marchio(due_aziende.iem) == "IEM Hub" and theme.marchio(due_aziende.zen) == "Hub"
    assert theme.marchio(None) == "Hub"
    oggetto, testo, html = modelli_email.componi("Da {{ marchio }}", "Ciao da {{ marchio }}", {}, due_aziende.iem)
    assert oggetto == "Da IEM Hub" and "IEM Hub" in testo and "IEM Hub" in html
    assert modelli_email.componi("Da {{ marchio }}", "x", {}, due_aziende.zen)[0] == "Da Hub"


def test_per_azienda_nelle_pagine_pubbliche(due_aziende, rf):
    """theme.per_azienda dà a una richiesta senza azienda (anonima) il tema dell'azienda del documento."""
    from django.contrib.auth.models import AnonymousUser

    from theme.context_processors import theme as contesto
    request = rf.get("/")
    request.user, request.azienda, request.session = AnonymousUser(), None, {}
    assert contesto(request)["theme"].get("brand") != "IEM Hub"
    theme.per_azienda(request, due_aziende.iem)
    assert contesto(request)["theme"]["brand"] == "IEM Hub" and request.azienda is None
