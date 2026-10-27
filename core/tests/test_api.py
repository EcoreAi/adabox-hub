import json

import pytest
from django.contrib.auth.models import Permission, User

from core.models import Azienda, TokenApi

BASE = "/api/v1/core/aziende/"


def _utente(*codenames, nome="api"):
    u = User.objects.create_user(nome, f"{nome}@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=codenames))
    return User.objects.get(pk=u.pk)


def _bearer(u):
    _, chiaro = TokenApi.genera(u, "test")
    return {"HTTP_AUTHORIZATION": f"Bearer {chiaro}"}


@pytest.fixture
def tutti(db):
    return _utente("view_azienda", "add_azienda", "change_azienda", "delete_azienda")


@pytest.fixture
def dati(db):
    for i, (nome, attiva) in enumerate([("Acme", True), ("Beta", False), ("Gamma", True)]):
        Azienda.objects.create(nome=nome, partita_iva=f"0{i}", attiva=attiva)


@pytest.mark.django_db
def test_autenticazione(client, tutti):
    assert client.get(BASE).status_code == 401
    client.force_login(tutti)
    assert client.get(BASE).status_code == 200
    client.logout()
    intestazioni = _bearer(tutti)
    assert client.get(BASE, **intestazioni).status_code == 200
    TokenApi.objects.update(attivo=False)
    assert client.get(BASE, **intestazioni).status_code == 401


@pytest.mark.django_db
def test_lista_e_filtri(client, tutti, dati):
    h = _bearer(tutti)
    corpo = client.get(BASE, **h).json()
    assert set(corpo) == {"count", "page", "per_page", "results"} and corpo["count"] == 4   # + azienda iniziale
    assert {"id", "nome", "partita_iva", "attiva"} <= set(corpo["results"][0])
    assert [a["nome"] for a in client.get(BASE, {"q": "acm"}, **h).json()["results"]] == ["Acme"]
    assert [a["nome"] for a in client.get(BASE, {"f_attiva": "0"}, **h).json()["results"]] == ["Beta"]
    pagina = client.get(BASE, {"o": "-nome", "per_page": 2, "p": 2}, **h).json()
    assert pagina["page"] == 2 and pagina["per_page"] == 2 and len(pagina["results"]) == 2
    assert client.get(BASE, {"per_page": 5000}, **h).json()["per_page"] == 200


@pytest.mark.django_db
def test_lista_senza_permesso(client):
    assert client.get(BASE, **_bearer(_utente())).status_code == 403


@pytest.mark.django_db
def test_crea(client, tutti):
    h = _bearer(tutti)
    r = client.post(BASE, json.dumps({"nome": "Nuova", "citta": "Roma"}), content_type="application/json", **h)
    assert r.status_code == 201 and r.json()["nome"] == "Nuova" and Azienda.objects.filter(nome="Nuova").exists()
    r = client.post(BASE, json.dumps({"nome": "", "email": "x"}), content_type="application/json", **h)
    assert r.status_code == 422 and set(r.json()["errori"]) == {"nome", "email"}
    r = client.post(BASE, json.dumps({"nome": "X"}), content_type="application/json", **_bearer(_utente("view_azienda", nome="solo")))
    assert r.status_code == 403


@pytest.mark.django_db
def test_leggi_modifica_elimina(client, tutti, dati):
    h = _bearer(tutti)
    acme = Azienda.objects.get(nome="Acme")
    assert client.get(f"{BASE}{acme.pk}/", **h).json()["partita_iva"] == "00"
    r = client.patch(f"{BASE}{acme.pk}/", json.dumps({"citta": "Cagliari"}), content_type="application/json", **h)
    assert r.status_code == 200
    acme.refresh_from_db()
    assert acme.citta == "Cagliari" and acme.nome == "Acme" and acme.partita_iva == "00" and acme.attiva
    assert client.delete(f"{BASE}{acme.pk}/", **h).status_code == 204
    assert not Azienda.objects.filter(pk=acme.pk).exists()
    assert client.get(f"{BASE}{acme.pk}/", **h).status_code == 404


@pytest.mark.django_db
def test_x_azienda(client, tutti, dati):
    estranea = Azienda.objects.create(nome="Estranea")
    tutti.profilo.aziende.remove(estranea)
    h = _bearer(tutti)
    assert client.get(BASE, HTTP_X_AZIENDA=str(estranea.pk), **h).status_code == 403
    consentita = tutti.profilo.aziende.first()
    assert client.get("/api/v1/me/", HTTP_X_AZIENDA=str(consentita.pk), **h).json()["azienda"]["id"] == consentita.pk


@pytest.mark.django_db
def test_me_e_moduli(client, tutti, superuser):
    client.logout()
    me = client.get("/api/v1/me/", **_bearer(tutti)).json()
    assert me["username"] == "api" and me["aziende"] and "app" in me
    assert client.get("/api/v1/moduli/", **_bearer(tutti)).status_code == 403
    r = client.get("/api/v1/moduli/", **_bearer(superuser))
    assert r.status_code == 200 and isinstance(r.json(), list)


@pytest.mark.django_db
def test_docs(client, utente):
    assert client.get("/api/v1/docs").status_code == 302
    client.force_login(utente)
    assert client.get("/api/v1/docs").status_code == 200


@pytest.mark.django_db
def test_vista_senza_api(client, superuser):
    assert client.get("/core/profili/").status_code == 200
    assert client.get("/api/v1/core/profili/").status_code == 404
