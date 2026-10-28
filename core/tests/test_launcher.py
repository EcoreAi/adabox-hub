import pytest
from django.urls import reverse

from core.registry import modules
from core.registry.manifest import Manifest


@pytest.fixture
def con_app(monkeypatch):
    m = Manifest(slug="alfa", percorso=None, name="Alfa", version="1.0.0", min_core="1.0", summary="Prova alfa",
                 application=True, icon="check", menu=[{"label": "Aziende", "url_name": "core:aziende_lista"}])
    monkeypatch.setattr(modules, "manifests_attivi", lambda: {"alfa": m})


@pytest.fixture
def senza_app(monkeypatch):
    monkeypatch.setattr(modules, "manifests_attivi", lambda: {})


@pytest.mark.django_db
def test_launcher_mostra_le_app(client, utente, con_app):
    client.force_login(utente)
    html = client.get(reverse("core:launcher")).content.decode()
    assert "Alfa" in html and "Prova alfa" in html and reverse("core:aziende_lista") in html
    assert "#icon-check" in html and "ui-empty" not in html


@pytest.mark.django_db
def test_launcher_vuoto_per_utente(client, utente, senza_app):
    client.force_login(utente)
    html = client.get(reverse("core:launcher")).content.decode()
    assert "ui-empty" in html and "/moduli/" not in html


@pytest.mark.django_db
def test_launcher_voci_del_kernel(client, superuser, senza_app):
    html = client.get(reverse("core:launcher")).content.decode()
    assert reverse("core:aziende_lista") in html and reverse("core:stile") in html
