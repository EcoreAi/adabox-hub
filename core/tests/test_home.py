"""La prima pagina (`/` e dopo il login) è la prima voce della barra in alto come la vede l'utente."""
import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from core import barra
from core.models import ProfiloUtente


def _home(client):
    r = client.get("/")
    assert r.status_code == 302
    return r["Location"]


@pytest.mark.django_db
def test_senza_scelta_della_barra_va_alla_chat(client, superuser):
    assert _home(client) == reverse("ai:chat")


@pytest.mark.django_db
def test_senza_app_in_testa_va_alla_dashboard(client, superuser, settings):
    settings.NAV_APP_IN_TESTA = []
    assert _home(client) == reverse("core:dashboard")


@pytest.mark.django_db
def test_barra_dell_azienda_che_comincia_dalla_dashboard(client, superuser):
    barra.scrivi(["dashboard", "ai", "crm"], 6)
    assert _home(client) == reverse("core:dashboard")
    client.logout()
    r = client.post(reverse("login"), {"username": "root", "password": "pass12345!"}, REMOTE_ADDR="10.0.0.1", follow=True)
    assert [url for url, _ in r.redirect_chain] == [reverse("core:home"), reverse("core:dashboard")]


@pytest.mark.django_db
def test_vale_la_barra_della_persona_e_non_quella_dell_azienda(client, superuser):
    barra.scrivi(["dashboard", "ai"], 6)
    ProfiloUtente.objects.update_or_create(utente=superuser, defaults={"barra": {"fisse": ["crm", "dashboard"], "completa": True}})
    assert _home(client) == reverse("crm:opportunita_kanban")


@pytest.mark.django_db
def test_prima_voce_non_vista_si_passa_alla_successiva(client, db):
    barra.scrivi(["crm", "todo", "dashboard"], 6)
    u = User.objects.create_user("lia", "lia@example.com", "pass12345!")
    u.user_permissions.add(Permission.objects.get(codename="view_attivita", content_type__app_label="todo"))
    client.force_login(u)
    assert _home(client) == reverse("todo:attivita_lista")          # il CRM non lo vede


@pytest.mark.django_db
def test_barra_vuota_va_alla_dashboard(client, superuser):
    barra.scrivi([], 6, nascoste=["dashboard", "ai"])
    assert _home(client) == reverse("core:dashboard")             # barra vuota: comunque una pagina
