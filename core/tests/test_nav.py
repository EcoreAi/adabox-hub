from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Permission, User
from django.test import RequestFactory
from django.urls import reverse

from core.registry import modules
from core.registry.manifest import Manifest
from core.registry.urls import patterns_moduli


def _m(slug, application, menu):
    return Manifest(slug=slug, percorso=None, name=slug.title(), version="1.0.0", min_core="1.0",
                    summary=f"Riassunto {slug}", application=application, menu=menu)


MENU = [{"label": "Aziende", "url_name": "core:aziende_lista", "permission": "core.view_azienda"},
        {"label": "Stile", "url_name": "core:stile", "permission": "core.delete_azienda"}]


@pytest.fixture(autouse=True)
def finti(monkeypatch):
    attivi = {"alfa": _m("alfa", True, MENU), "beta": _m("beta", False, MENU[:1])}
    monkeypatch.setattr(modules, "manifests_attivi", lambda: attivi)


def _utente(client, *codenames):
    u = User.objects.create_user("nav", "nav@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=codenames))
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    return u


def _nav(r):
    return [v["label"] for v in r.context["theme"]["nav"] if v["url_name"] != "core:dashboard"]


@pytest.mark.django_db
def test_nav_solo_con_permesso(client):
    _utente(client)
    assert _nav(client.get(reverse("core:launcher"))) == []


@pytest.mark.django_db
def test_nav_con_permesso(client):
    _utente(client, "view_azienda")
    r = client.get(reverse("core:launcher"))
    assert _nav(r) == ["Alfa"]
    assert [v["label"] for v in r.context["apps"][0]["menu"]] == ["Aziende"]


@pytest.mark.django_db
def test_nav_superuser(client, superuser):
    r = client.get(reverse("core:launcher"))
    assert _nav(r) == ["Alfa"]
    assert [v["label"] for v in r.context["apps"][0]["menu"]] == ["Aziende", "Stile"]


@pytest.mark.django_db
def test_app_corrente(utente):
    request = RequestFactory().get("/core/aziende/")
    request.user = utente
    request.resolver_match = SimpleNamespace(namespace="core")
    assert modules.app_corrente(request) is None
    request.user = User.objects.create_superuser("root2", "r@example.com", "pass12345!")
    request.resolver_match = SimpleNamespace(namespace="alfa")
    app = modules.app_corrente(request)
    assert app["slug"] == "alfa"
    assert [(v["label"], v["attiva"]) for v in app["menu"]] == [("Aziende", True), ("Stile", False)]


@pytest.mark.django_db
def test_barra_dell_app_nel_contesto(client, superuser, monkeypatch):
    monkeypatch.setattr(modules, "app_corrente", lambda request, apps=None: {**apps[0], "menu": [
        {**v, "attiva": False} for v in apps[0]["menu"]]})
    html = client.get(reverse("core:aziende_lista")).content.decode()
    assert 'class="ui-appbar"' in html and "Alfa" in html


def test_patterns_moduli_vuoto(settings):
    settings.ADDONS_ATTIVI = []
    assert patterns_moduli() == []
