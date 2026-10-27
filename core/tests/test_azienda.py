import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

from core.azienda import CHIAVE_SESSIONE
from core.middleware import AziendaCorrenteMiddleware
from core.models import Azienda


def _richiesta(user):
    request = RequestFactory().get("/")
    SessionMiddleware(lambda r: HttpResponse()).process_request(request)
    request.user = user
    AziendaCorrenteMiddleware(lambda r: HttpResponse())(request)
    return request


@pytest.fixture
def seconda(db, utente):
    a = Azienda.objects.create(nome="Zeta Srl")
    utente.profilo.aziende.add(a)
    return a


def test_anonimo_senza_azienda():
    assert _richiesta(AnonymousUser()).azienda is None


@pytest.mark.django_db
def test_utente_con_predefinita(utente):
    assert _richiesta(utente).azienda == utente.profilo.azienda_predefinita


@pytest.mark.django_db
def test_cambia_azienda_consentita(client, utente, seconda):
    client.force_login(utente)
    r = client.post(reverse("core:cambia_azienda"), {"azienda": seconda.pk, "next": "/profilo/"})
    assert r.status_code == 302 and r["Location"] == "/profilo/"
    assert client.session[CHIAVE_SESSIONE] == seconda.pk
    r = client.get(reverse("core:home"))
    assert r.wsgi_request.azienda == seconda


@pytest.mark.django_db
def test_cambia_azienda_next_esterno_ignorato(client, utente, seconda):
    client.force_login(utente)
    r = client.post(reverse("core:cambia_azienda"), {"azienda": seconda.pk, "next": "https://evil.example/"})
    assert r["Location"] == "/"


@pytest.mark.django_db
def test_cambia_azienda_non_consentita(client, utente):
    altra = Azienda.objects.create(nome="Altra")
    utente.profilo.aziende.remove(altra)
    client.force_login(utente)
    assert client.post(reverse("core:cambia_azienda"), {"azienda": altra.pk}).status_code == 403


@pytest.mark.django_db
def test_cambia_azienda_inesistente_e_get(client, utente):
    client.force_login(utente)
    assert client.post(reverse("core:cambia_azienda"), {"azienda": 9999}).status_code == 404
    assert client.get(reverse("core:cambia_azienda")).status_code == 405


@pytest.mark.django_db
def test_selettore_solo_con_piu_aziende(utente, seconda):
    request = RequestFactory().get("/")
    una = render_to_string("core/partials/_aziende.html", {"aziende": [seconda], "azienda": seconda}, request)
    assert "<select" not in una
    due = render_to_string("core/partials/_aziende.html",
                           {"aziende": list(utente.profilo.aziende.all()), "azienda": seconda}, request)
    assert "<select" in due and "Zeta Srl" in due
