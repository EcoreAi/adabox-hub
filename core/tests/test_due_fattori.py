import time

import pyotp
import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from core import due_fattori as df2
from core.models import DueFattori

PASSWORD = "giusta12345!"


@pytest.fixture
def mario(db):
    return User.objects.create_user("mario", "mario@example.com", PASSWORD)


def _attiva(utente):
    df = df2.prepara(utente)
    df.attiva_dal = timezone.now()
    df.save(update_fields=["attiva_dal"])
    return df


def _codice(df, scarto=0):
    return pyotp.TOTP(df2.segreto(df)).at(time.time() + scarto)


def _password(client, **extra):
    return client.post(reverse("login"), {"username": "mario", "password": PASSWORD, **extra}, REMOTE_ADDR="10.0.0.1")


def _esci_tenendo_il_dispositivo(client):
    """client.logout() del test svuota anche i cookie: il browser vero tiene quello del dispositivo."""
    valore = client.cookies[df2.COOKIE_FIDATO].value
    client.logout()
    client.cookies[df2.COOKIE_FIDATO] = valore


def _collegato(client):
    return "_auth_user_id" in client.session


def test_senza_2fa_accesso_normale(client, mario):
    assert _password(client).status_code == 302 and _collegato(client)


def test_password_giusta_non_basta(client, mario):
    df = _attiva(mario)
    r = _password(client)
    assert r.url == reverse("due_fattori_accesso") and not _collegato(client)
    assert client.get(reverse("core:profilo")).status_code == 302 and not _collegato(client)
    r = client.post(r.url, {"codice": "000000" if _codice(df) != "000000" else "111111"})
    assert r.status_code == 200 and not _collegato(client) and "non è corretto" in r.content.decode()
    client.post(reverse("due_fattori_accesso"), {"codice": _codice(df)})
    assert _collegato(client) and int(client.session["_auth_user_id"]) == mario.pk


def test_pagina_codice_senza_password(client, mario):
    _attiva(mario)
    assert client.get(reverse("due_fattori_accesso")).url == reverse("login")


def test_codice_non_si_riusa(client, mario):
    df = _attiva(mario)
    codice = _codice(df)
    _password(client)
    client.post(reverse("due_fattori_accesso"), {"codice": codice})
    assert _collegato(client)
    client.logout()
    _password(client)
    client.post(reverse("due_fattori_accesso"), {"codice": codice})
    assert not _collegato(client)


def test_blocco_dopo_troppi_errori(client, mario, settings):
    df = _attiva(mario)
    _password(client)
    sbagliato = "000000" if _codice(df) != "000000" else "111111"
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        assert client.post(reverse("due_fattori_accesso"), {"codice": sbagliato}).status_code == 200
    assert client.post(reverse("due_fattori_accesso"), {"codice": sbagliato}).status_code == 429
    assert client.post(reverse("due_fattori_accesso"), {"codice": _codice(df)}).status_code == 429     # anche se giusto
    assert not _collegato(client)


def test_codice_di_recupero_una_volta_sola(client, mario):
    df = _attiva(mario)
    codici = df2.nuovi_codici(df)
    _password(client)
    client.post(reverse("due_fattori_accesso"), {"codice": codici[0].lower()})
    assert _collegato(client) and len(DueFattori.objects.get(pk=df.pk).codici_recupero) == 9
    assert "recupero" in mail.outbox[-1].subject
    client.logout()
    _password(client)
    client.post(reverse("due_fattori_accesso"), {"codice": codici[0]})
    assert not _collegato(client)


def test_dispositivo_fidato_e_revoca(client, mario):
    df = _attiva(mario)
    _password(client)
    client.post(reverse("due_fattori_accesso"), {"codice": _codice(df), "ricorda": "1"})
    assert df2.COOKIE_FIDATO in client.cookies and client.cookies[df2.COOKIE_FIDATO]["httponly"]
    _esci_tenendo_il_dispositivo(client)
    assert _password(client).url != reverse("due_fattori_accesso") and _collegato(client)
    client.post(reverse("core:due_fattori"), {"azione": "revoca_fidati"})
    _esci_tenendo_il_dispositivo(client)
    assert _password(client).url == reverse("due_fattori_accesso")


def test_cambio_password_invalida_il_dispositivo(client, mario):
    df = _attiva(mario)
    _password(client)
    client.post(reverse("due_fattori_accesso"), {"codice": _codice(df), "ricorda": "1"})
    _esci_tenendo_il_dispositivo(client)
    mario.set_password(PASSWORD)            # stessa password, sale nuovo: cambia l'impronta
    mario.save()
    assert _password(client).url == reverse("due_fattori_accesso")


def test_attivazione_dal_profilo(client, mario):
    client.force_login(mario)
    pagina = client.get(reverse("core:due_fattori")).content.decode()
    assert "<svg" in pagina and "Inquadra" in pagina
    df = DueFattori.objects.get(utente=mario)
    assert not df2.attiva(mario)
    client.post(reverse("core:due_fattori"), {"azione": "attiva", "codice": "12345"})
    assert not df2.attiva(mario)
    r = client.post(reverse("core:due_fattori"), {"azione": "attiva", "codice": _codice(df)}, follow=True)
    assert df2.attiva(mario) and "I tuoi codici di recupero" in r.content.decode()
    assert "attivata" in mail.outbox[-1].subject
    assert "I tuoi codici di recupero" not in client.get(reverse("core:due_fattori")).content.decode()   # una volta sola
    assert df2.segreto(df) not in DueFattori.objects.get(pk=df.pk).segreto_cifrato


def test_disattivazione_chiede_password_e_codice(client, mario):
    df = _attiva(mario)
    client.force_login(mario)
    client.post(reverse("core:due_fattori"), {"azione": "disattiva", "password": "no", "codice": _codice(df)})
    assert df2.attiva(mario)
    client.post(reverse("core:due_fattori"), {"azione": "disattiva", "password": PASSWORD, "codice": _codice(df)})
    assert not df2.attiva(mario)


def test_obbligo(client, mario, superuser):
    client.post(reverse("core:impostazioni"), {"modulo": "sicurezza", "obbligo": df2.TUTTI})
    assert df2.leggi_obbligo() == df2.TUTTI
    client.force_login(mario)
    assert client.get(reverse("core:dashboard")).url == reverse("core:due_fattori")
    assert client.get(reverse("core:due_fattori")).status_code == 200
    df = df2.prepara(mario)
    client.post(reverse("core:due_fattori"), {"azione": "attiva", "codice": _codice(df)})
    assert client.get(reverse("core:dashboard")).status_code == 200
    client.post(reverse("core:due_fattori"), {"azione": "disattiva", "password": PASSWORD, "codice": _codice(df, 30)})
    assert df2.attiva(mario)


def test_obbligo_solo_amministratori(client, mario, superuser):
    df2.scrivi_obbligo(df2.AMMINISTRATORI)
    assert client.get(reverse("core:dashboard")).url == reverse("core:due_fattori")
    client.force_login(mario)
    assert client.get(reverse("core:dashboard")).status_code == 200


def test_utente_normale_non_cambia_l_obbligo(client, mario):
    from django.contrib.auth.models import Permission
    mario.user_permissions.add(Permission.objects.get(codename="change_parametro"))
    client.force_login(mario)
    client.post(reverse("core:impostazioni"), {"modulo": "sicurezza", "obbligo": df2.TUTTI})
    assert df2.leggi_obbligo() == df2.NESSUNO


def test_admin_non_aggira_la_verifica(client, db):
    User.objects.create_superuser("mario", "m@example.com", PASSWORD)
    r = client.get("/admin/login/")
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
