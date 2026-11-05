"""I token dell'API: scadenza, sola lettura, limite ai moduli. Restringono l'utente, non lo allargano mai."""
import datetime

import pytest
from django.contrib.auth.models import Permission, User
from django.utils import timezone

from core.forms import TokenApiForm
from core.models import Azienda, TokenApi
from todo.models import Attivita

pytestmark = pytest.mark.django_db
OGGI = timezone.localdate()
URL = "/api/v1/todo/attivita/"


@pytest.fixture
def u():
    a = Azienda.objects.first()
    utente = User.objects.create_user("mario", "m@example.com", "x")
    utente.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=["todo", "contatti"]))
    utente.profilo.aziende.set([a])
    utente.profilo.azienda_predefinita = a
    utente.profilo.save()
    return User.objects.get(pk=utente.pk)


def _h(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _crea(client, token):
    return client.post(URL, '{"titolo": "X", "stato": "aperta"}', content_type="application/json", **_h(token))


def test_scaduto_non_autentica(client, u):
    _, ieri = TokenApi.genera(u, "a", scadenza=OGGI - datetime.timedelta(days=1))
    _, oggi = TokenApi.genera(u, "b", scadenza=OGGI)
    _, mai = TokenApi.genera(u, "c")
    assert client.get(URL, **_h(ieri)).status_code == 401
    assert client.get(URL, **_h(oggi)).status_code == 200
    assert client.get(URL, **_h(mai)).status_code == 200


def test_sola_lettura_legge_e_non_scrive(client, u):
    _, token = TokenApi.genera(u, "a", sola_lettura=True)
    a = Attivita.objects.create(azienda=u.profilo.azienda_predefinita, titolo="X")
    assert client.get(URL, **_h(token)).status_code == 200
    assert client.get(f"{URL}{a.pk}/", **_h(token)).status_code == 200
    assert _crea(client, token).status_code == 403
    assert client.patch(f"{URL}{a.pk}/", '{"titolo": "Y"}', content_type="application/json", **_h(token)).status_code == 403
    assert client.delete(f"{URL}{a.pk}/", **_h(token)).status_code == 403
    assert client.post(f"{URL}{a.pk}/azioni/segna_fatta/", **_h(token)).status_code == 403
    a.refresh_from_db()
    assert a.titolo == "X" and Attivita.objects.count() == 1


def test_limitato_a_un_modulo(client, u):
    _, token = TokenApi.genera(u, "a", moduli=["contatti"])
    assert client.get("/api/v1/contatti/contatti/", **_h(token)).status_code == 200
    r = client.get(URL, **_h(token))
    assert r.status_code == 403 and "todo" in r.content.decode()
    assert _crea(client, token).status_code == 403


def test_il_token_non_allarga_i_permessi(client, u):
    _, token = TokenApi.genera(u, "a", moduli=["acquisti"])
    assert client.get("/api/v1/acquisti/ordini/", **_h(token)).status_code == 403
    u.user_permissions.remove(*Permission.objects.filter(content_type__app_label="todo"))
    _, pieno = TokenApi.genera(User.objects.get(pk=u.pk), "b")
    assert client.get(URL, **_h(pieno)).status_code == 403


def test_pieni_poteri_se_non_si_limita_e_chi_era_gia_li(client, u):
    _, token = TokenApi.genera(u, "a")
    assert _crea(client, token).status_code == 201


def test_me_resta_leggibile(client, u):
    _, token = TokenApi.genera(u, "a", sola_lettura=True, moduli=["contatti"])
    assert client.get("/api/v1/me/", **_h(token)).status_code == 200


def test_moduli_del_superuser_non_con_un_token_limitato(client, u):
    root = User.objects.create_superuser("root", "r@example.com", "x")
    _, limitato = TokenApi.genera(root, "a", moduli=["todo"])
    _, pieno = TokenApi.genera(root, "b")
    assert client.get("/api/v1/moduli/", **_h(limitato)).status_code == 403
    assert client.get("/api/v1/moduli/", **_h(pieno)).status_code == 200


def test_la_sessione_del_browser_non_ha_questi_limiti(client, u):
    TokenApi.genera(u, "a", sola_lettura=True)
    client.force_login(u)
    assert client.get(URL).status_code == 200                     # con la sessione contano i permessi dell'utente, non il token


def test_il_form_parte_prudente(u):
    form = TokenApiForm(utente=u)
    assert form.fields["sola_lettura"].initial is True and form.fields["durata"].initial == "90"


def test_il_form_calcola_la_scadenza_e_rifiuta_moduli_non_visibili(u):
    form = TokenApiForm({"nome": "t", "durata": "30"}, utente=u)
    assert form.is_valid() and form.scadenza() == OGGI + datetime.timedelta(days=30)
    senza = TokenApiForm({"nome": "t", "durata": ""}, utente=u)
    assert senza.is_valid() and senza.scadenza() is None
    assert not TokenApiForm({"nome": "t", "durata": "7", "moduli": ["acquisti"]}, utente=u).is_valid()


def test_dalla_pagina_del_profilo(client, u):
    client.force_login(u)
    assert "Solo questi moduli" in client.get("/profilo/").content.decode()
    assert client.post("/profilo/token/", {"nome": "integrazione", "durata": "7", "sola_lettura": "on"}).status_code == 302
    t = TokenApi.objects.get(nome="integrazione")
    assert t.sola_lettura and t.scadenza == OGGI + datetime.timedelta(days=7) and t.moduli == []
    assert "Leggere" in client.get("/profilo/").content.decode()


def test_scaduto_si_vede_nella_pagina(client, u):
    TokenApi.genera(u, "vecchio", scadenza=OGGI - datetime.timedelta(days=1))
    client.force_login(u)
    assert "Scaduto" in client.get("/profilo/").content.decode()
