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


@pytest.mark.django_db
def test_azienda_predefinita(client, utente):
    from core.models import Azienda
    client.force_login(utente)
    assert "Azienda predefinita" not in client.get(reverse("core:profilo")).content.decode()   # una sola azienda
    zeta = Azienda.objects.create(nome="Zeta Srl")
    utente.profilo.aziende.add(zeta)
    assert "Azienda predefinita" in client.get(reverse("core:profilo")).content.decode()
    client.post(reverse("core:azienda_predefinita"), {"azienda_predefinita": zeta.pk})
    utente.profilo.refresh_from_db()
    assert utente.profilo.azienda_predefinita == zeta


@pytest.mark.django_db
def test_azienda_predefinita_non_consentita(client, utente):
    from core.models import Azienda
    estranea = Azienda.objects.create(nome="Estranea")
    utente.profilo.aziende.remove(estranea)
    prima = utente.profilo.azienda_predefinita
    client.force_login(utente)
    client.post(reverse("core:azienda_predefinita"), {"azienda_predefinita": estranea.pk})
    utente.profilo.refresh_from_db()
    assert utente.profilo.azienda_predefinita == prima
