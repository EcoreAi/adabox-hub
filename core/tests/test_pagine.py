import pytest
from django.conf import settings
from django.urls import reverse


@pytest.mark.django_db
def test_home_richiede_login(client):
    r = client.get(reverse("core:home"))
    assert r.status_code == 302
    assert r["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_home_da_staff(client, staff):
    r = client.get(reverse("core:dashboard"))
    assert r.status_code == 200
    assert settings.THEME["brand"] in r.content.decode()  # brand dal THEME dei settings


@pytest.mark.django_db
def test_catalogo_stile_mostra_ogni_componente(client, staff):
    r = client.get(reverse("core:stile"))
    assert r.status_code == 200
    html = r.content.decode()
    for classe in ["ui-btn-primary", "ui-btn-secondary", "ui-btn-ghost", "ui-btn-danger",
                   "ui-icon-btn", "ui-input", "ui-pill-ok", "ui-pill-warn", "ui-pill-danger",
                   "ui-kpi", "ui-card", "ui-table", "ui-empty", "ui-alert-success", "ui-link"]:
        assert classe in html, classe
    assert "uiToast(" in html
    assert "<pre" in html  # snippet da copiare


@pytest.mark.django_db
def test_profilo_modifica_nome(client, staff):
    r = client.get(reverse("core:profilo"))
    assert r.status_code == 200
    r = client.post(reverse("core:profilo"), {"first_name": "Anna", "last_name": "Neri", "email": "a@n.it"})
    assert r.status_code == 302
    staff.refresh_from_db()
    assert staff.first_name == "Anna" and staff.email == "a@n.it"
