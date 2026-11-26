"""Aziende dei nuovi utenti: con più aziende attive il modulo parte senza spunte; AZIENDE_NUOVI_UTENTI per il resto."""
import pytest
from django.contrib.auth.models import User
from django.test import override_settings

from core.models import Azienda, Ruolo


@pytest.fixture
def due(db):
    a = Azienda.objects.create(nome="Zen Park")
    b = Azienda.objects.create(nome="IEM")
    return a, b


def _dati(**extra):
    d = {"first_name": "Mario", "last_name": "Rossi", "email": "mario@example.com", "username": "", "is_active": "on"}
    d.update(extra)
    return d


def test_con_due_aziende_il_modulo_parte_senza_spunte(due, superuser, client):
    r = client.get("/utenti/nuovo/")
    assert list(r.context["form"].initial["aziende"]) == []
    assert 'name="aziende"' in r.content.decode() and " checked" not in r.content.decode().split('name="aziende"', 1)[1].split("</ul>", 1)[0]


def test_con_due_aziende_senza_scelta_errore_e_nessun_utente(due, superuser, client):
    r = client.post("/utenti/nuovo/", _dati())
    assert r.status_code == 200
    assert "Scegli almeno un&#x27;azienda." in r.content.decode() or "Scegli almeno un'azienda." in r.content.decode()
    assert not User.objects.filter(email="mario@example.com").exists()


def test_con_due_aziende_una_scelta_e_la_predefinita(due, superuser, client):
    a, b = due
    client.post("/utenti/nuovo/", _dati(aziende=[b.pk]))
    p = User.objects.get(email="mario@example.com").profilo
    assert list(p.aziende.all()) == [b] and p.azienda_predefinita == b


@pytest.mark.parametrize("impostazione", ["tutte", "nessuna"])
def test_il_modulo_da_esattamente_le_aziende_scelte(due, superuser, client, impostazione):
    a, b = due
    with override_settings(AZIENDE_NUOVI_UTENTI=impostazione):
        client.post("/utenti/nuovo/", _dati(aziende=[a.pk]))
    p = User.objects.get(email="mario@example.com").profilo
    assert list(p.aziende.all()) == [a] and p.azienda_predefinita == a


def test_con_una_azienda_e_spuntata_e_si_salva_come_prima(db, superuser, client):
    a = Azienda.objects.filter(attiva=True).get()
    r = client.get("/utenti/nuovo/")
    assert list(r.context["form"].initial["aziende"]) == [a]
    client.post("/utenti/nuovo/", _dati(aziende=[a.pk]))
    assert list(User.objects.get(email="mario@example.com").profilo.aziende.all()) == [a]


def test_con_una_azienda_senza_scelta_si_salva(db, superuser, client):
    client.post("/utenti/nuovo/", _dati())
    assert User.objects.filter(email="mario@example.com").exists()


def test_la_scheda_di_un_utente_esistente_mostra_le_sue_aziende(due, superuser, client):
    a, b = due
    u = User.objects.create_user("lia", "lia@example.com", "x")
    u.profilo.aziende.set([b])
    r = client.get(f"/utenti/{u.pk}/")
    assert list(r.context["form"].initial["aziende"]) == [b]


@override_settings(AZIENDE_NUOVI_UTENTI="nessuna")
def test_nessuna_con_due_aziende_create_user_senza_aziende(due):
    u = User.objects.create_user("x", "x@example.com", "x")
    assert u.profilo.aziende.count() == 0 and u.profilo.azienda_predefinita is None
    s = User.objects.create_superuser("s", "s@example.com", "x")
    assert s.profilo.aziende.count() == Azienda.objects.filter(attiva=True).count() and s.profilo.azienda_predefinita


@override_settings(AZIENDE_NUOVI_UTENTI="nessuna")
def test_nessuna_con_una_azienda_non_cambia(db):
    u = User.objects.create_user("x", "x@example.com", "x")
    assert u.profilo.aziende.count() == 1


def test_predefinita_create_user_da_tutte_le_aziende(due):
    u = User.objects.create_user("x", "x@example.com", "x")
    assert u.profilo.aziende.count() == Azienda.objects.filter(attiva=True).count() and u.profilo.azienda_predefinita
