import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
def test_login_in_stile_con_brand(client):
    with override_settings(THEME={"brand": "Acme", "mark": "AC"}):
        r = client.get(reverse("login"))
    assert r.status_code == 200
    html = r.content.decode()
    assert "ui-login-card" in html
    assert '<span class="mark">AC</span>' in html
    assert "Acme" in html


@pytest.mark.django_db
def test_login_errato_mostra_alert(client):
    r = client.post(reverse("login"), {"username": "x", "password": "y"})
    assert r.status_code == 200
    assert "Credenziali non valide" in r.content.decode()


@pytest.mark.django_db
def test_cambio_password_richiede_login_e_usa_tema(client):
    r = client.get(reverse("password_change"))
    assert r.status_code == 302
    u = User.objects.create_user("anna", "a@example.com", "pass12345!")
    client.force_login(u)
    r = client.get(reverse("password_change"))
    assert r.status_code == 200
    assert "ui-card" in r.content.decode()


@pytest.mark.django_db
def test_404_usa_il_tema(client):
    r = client.get("/pagina-che-non-esiste/")
    assert r.status_code == 404
    assert "ui-card" in r.content.decode()


@pytest.mark.django_db
def test_lockout_mostra_minuti(client):
    from django.test import RequestFactory
    from axes.helpers import get_lockout_response
    r = get_lockout_response(RequestFactory().get("/"), credentials={"username": "x"})
    html = r.content.decode()
    assert r.status_code == 429
    assert "ui-login-card" in html
    assert "15 minuti" in html


def test_500_autonoma_senza_contesto():
    from django.template.loader import render_to_string
    html = render_to_string("500.html")
    assert "ui-card" in html and "500" in html


@pytest.mark.django_db
def test_lockout_con_utente_loggato_mostra_il_messaggio():
    from django.test import RequestFactory
    from axes.helpers import get_lockout_response
    request = RequestFactory().get("/")
    request.user = User.objects.create_user("anna", "a@example.com", "pass12345!")
    r = get_lockout_response(request, credentials={"username": "x"})
    html = r.content.decode()
    assert r.status_code == 429
    assert "Troppi tentativi di accesso falliti" in html
    assert "15 minuti" in html
