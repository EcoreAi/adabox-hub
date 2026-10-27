import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from core.models import TokenApi


@pytest.mark.django_db
def test_token_mostrato_una_volta(client, utente):
    client.force_login(utente)
    r = client.post(reverse("core:token_nuovo"), {"nome": "cli"})
    assert r.status_code == 302
    token = TokenApi.objects.get(utente=utente, nome="cli")
    html = client.get(reverse("core:profilo")).content.decode()
    chiaro = html.split('id="token-chiaro">')[1].split("<")[0]
    assert TokenApi.verifica(chiaro) == token
    seconda = client.get(reverse("core:profilo")).content.decode()
    assert chiaro not in seconda and "cli" in seconda


@pytest.mark.django_db
def test_revoca(client, utente):
    token, _ = TokenApi.genera(utente, "cli")
    client.force_login(utente)
    assert client.post(reverse("core:token_revoca", args=[token.pk])).status_code == 302
    token.refresh_from_db()
    assert token.attivo is False


@pytest.mark.django_db
def test_revoca_token_altrui_404(client, utente):
    altro = User.objects.create_user("altro", "a@example.com", "pass12345!")
    token, _ = TokenApi.genera(altro, "suo")
    client.force_login(utente)
    assert client.post(reverse("core:token_revoca", args=[token.pk])).status_code == 404
    token.refresh_from_db()
    assert token.attivo
