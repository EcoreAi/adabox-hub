import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from core import parametri
from core.models import Azienda, Parametro
from core.registry import modules
from core.registry.manifest import Manifest

SETTINGS = [
    {"chiave": "giorni", "label": "Giorni di preavviso", "tipo": "intero", "default": 2, "per_azienda": True},
    {"chiave": "soglia", "label": "Soglia", "tipo": "decimale", "default": "1.50"},
    {"chiave": "attivo", "label": "Attivo", "tipo": "booleano", "default": True},
    {"chiave": "dal", "label": "Dal", "tipo": "data"},
    {"chiave": "modo", "label": "Modo", "tipo": "scelta", "scelte": [["a", "A"], ["b", "B"]], "default": "a"},
]


@pytest.fixture(autouse=True)
def finti(monkeypatch):
    m = Manifest(slug="alfa", percorso=None, name="Alfa", version="1.0.0", min_core="1.0", application=True,
                 menu=[{"label": "Aziende", "url_name": "core:aziende_lista"}], settings=SETTINGS)
    monkeypatch.setattr(modules, "manifests_attivi", lambda: {"alfa": m})


@pytest.fixture
def aziende(db):
    return Azienda.objects.get(pk=1), Azienda.objects.create(nome="Zeta")


def test_default_e_tipi(aziende):
    assert parametri.leggi("alfa.giorni") == 2
    assert parametri.leggi("alfa.soglia") == Decimal("1.50")
    assert parametri.leggi("alfa.attivo") is True
    assert parametri.leggi("alfa.dal") is None
    with pytest.raises(KeyError):
        parametri.leggi("alfa.inesistente")


def test_precedenza_azienda_globale_default(aziende):
    prima, zeta = aziende
    parametri.scrivi("alfa.giorni", 5)                       # globale
    parametri.scrivi("alfa.giorni", 9, azienda=zeta)
    assert parametri.leggi("alfa.giorni", zeta) == 9
    assert parametri.leggi("alfa.giorni", prima) == 5
    assert parametri.leggi("alfa.giorni") == 5


def test_non_per_azienda_scritto_globale(aziende):
    _, zeta = aziende
    parametri.scrivi("alfa.soglia", Decimal("2.25"), azienda=zeta)
    assert Parametro.objects.get(chiave="alfa.soglia").azienda is None
    parametri.scrivi("alfa.dal", datetime.date(2026, 1, 31))
    assert parametri.leggi("alfa.dal", zeta) == datetime.date(2026, 1, 31)


def _utente(client, *codenames):
    u = User.objects.create_user("imp", "imp@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=codenames))
    client.force_login(User.objects.get(pk=u.pk))
    return u


@pytest.mark.django_db
def test_pagina_permessi(client):
    _utente(client)
    assert client.get(reverse("core:impostazioni")).status_code == 403


@pytest.mark.django_db
def test_pagina_salva(client, aziende):
    _utente(client, "change_parametro")
    html = client.get(reverse("core:impostazioni")).content.decode()
    assert 'id="alfa"' in html and "Giorni di preavviso" in html and 'value="2"' in html
    r = client.post(reverse("core:impostazioni"), {"modulo": "alfa", "giorni": "7", "soglia": "3.10",
                                                    "attivo": "", "dal": "2026-11-01", "modo": "b"})
    assert r.status_code == 302 and r["Location"].endswith("#alfa")
    prima, zeta = aziende
    assert parametri.leggi("alfa.giorni", prima) == 7 and parametri.leggi("alfa.giorni", zeta) == 2
    assert parametri.leggi("alfa.attivo") is False and parametri.leggi("alfa.modo") == "b"


@pytest.mark.django_db
def test_pagina_errori_e_modulo_sconosciuto(client):
    _utente(client, "change_parametro")
    r = client.post(reverse("core:impostazioni"), {"modulo": "alfa", "giorni": "x", "soglia": "1", "modo": "a"})
    assert r.status_code == 200 and "ui-field-error" in r.content.decode()
    assert client.post(reverse("core:impostazioni"), {"modulo": "beta"}).status_code == 400


@pytest.mark.django_db
def test_link_impostazioni_nella_barra_dell_app(client):
    u = _utente(client, "change_parametro")
    app = modules.app_visibili(User.objects.get(pk=u.pk))[0]
    assert app["settings_url"] == "/impostazioni/#alfa"
