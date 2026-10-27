import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse

from core.models import Cliente


@pytest.fixture
def staff(client):
    u = User.objects.create_user("staff", "s@example.com", "pass12345!", is_staff=True, is_superuser=True)
    client.force_login(u)
    return u


@pytest.mark.django_db
def test_home_richiede_login(client):
    r = client.get(reverse("core:home"))
    assert r.status_code == 302
    assert r["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_home_mostra_kpi_e_tabella(client, staff):
    Cliente.objects.create(nome="Rossi Srl", email="info@rossi.it", attivo=True)
    Cliente.objects.create(nome="Bianchi Spa", email="info@bianchi.it", attivo=False)
    r = client.get(reverse("core:home"))
    assert r.status_code == 200
    html = r.content.decode()
    assert "ui-kpis" in html and "ui-table" in html
    assert "Rossi Srl" in html and "Bianchi Spa" in html
    assert settings.THEME["brand"] in html  # brand dal THEME dei settings


@pytest.mark.django_db
def test_home_vuota_mostra_empty_state(client, staff):
    r = client.get(reverse("core:home"))
    assert "ui-empty" in r.content.decode()


@pytest.mark.django_db
def test_admin_cliente_changelist_e_change(client, staff):
    c = Cliente.objects.create(nome="Verdi", email="v@example.com")
    assert client.get(reverse("admin:core_cliente_changelist")).status_code == 200
    assert client.get(reverse("admin:core_cliente_change", args=[c.pk])).status_code == 200
    assert client.get(reverse("admin:core_cliente_add")).status_code == 200


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
