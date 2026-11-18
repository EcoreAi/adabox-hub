"""Login inviato con un token vecchio (app ripresa dal telefono, pagina rimasta aperta): niente 403, si ricarica."""
from django.test import Client
from django.urls import reverse


def test_login_con_token_vecchio_torna_al_login(db):
    client = Client(enforce_csrf_checks=True)
    url = reverse("login") + "?next=/tasca/%3Fda%3Dapp"
    client.get(url)                                                  # il cookie csrftoken di adesso
    r = client.post(url, {"username": "x", "password": "y", "csrfmiddlewaretoken": "a" * 64})
    assert r.status_code == 302 and r["Location"] == url
    pagina = client.get(url).content.decode()
    assert "rimasta aperta troppo a lungo" in pagina


def test_altri_moduli_restano_protetti(db):
    client = Client(enforce_csrf_checks=True)
    client.get(reverse("login"))
    r = client.post("/accounts/logout/", {"csrfmiddlewaretoken": "a" * 64})
    assert r.status_code == 403
