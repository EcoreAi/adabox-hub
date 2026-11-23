"""Mittente delle email per azienda (Azienda.email_mittente_nome / email_mittente): modelli_email e chatter."""
import types

import pytest
from django.contrib.auth.models import User
from django.core import mail

from core import chatter, modelli_email
from core.models import Azienda


def _az(nome="", indirizzo=""):
    return types.SimpleNamespace(email_mittente_nome=nome, email_mittente=indirizzo)


def test_mittente(settings):
    settings.DEFAULT_FROM_EMAIL = "Hub <noreply@hub.example.it>"
    assert modelli_email.mittente(_az()) is None and modelli_email.mittente(None) is None
    assert modelli_email.mittente(_az("Zen Park", "offerte@zenpark.it")) == "Zen Park <offerte@zenpark.it>"
    assert modelli_email.mittente(_az(indirizzo="info@iem.it")) == "info@iem.it"
    assert modelli_email.mittente(_az("IEM")) == "IEM <noreply@hub.example.it>"     # il nome sull'indirizzo dell'istanza
    assert modelli_email.mittente(_az("Rossi, Bianchi & C.", "a@b.it")) == '"Rossi, Bianchi & C." <a@b.it>'


@pytest.fixture
def aziende(db, settings):
    settings.DEFAULT_FROM_EMAIL = "noreply@hub.example.it"
    return (Azienda.objects.create(nome="Zen Park", email_mittente_nome="Zen Park", email_mittente="offerte@zenpark.it"),
            Azienda.objects.create(nome="Senza"))


def test_messaggio_da_con_il_mittente_dell_azienda(aziende):
    zen, senza = aziende
    email = modelli_email.messaggio_da("Offerta {{ numero }}", "Ciao", {"numero": "7"}, zen, ["c@x.it"])
    assert email.from_email == "Zen Park <offerte@zenpark.it>" and email.subject == "Offerta 7"
    email.send()
    assert mail.outbox[0].from_email == "Zen Park <offerte@zenpark.it>"
    assert modelli_email.messaggio_da("O", "C", {}, senza, ["c@x.it"]).from_email == "noreply@hub.example.it"


def test_messaggio_da_accetta_un_altro_mittente(aziende):
    """Prima from_email= tra gli argomenti in più dava TypeError (il terzo argomento era già None)."""
    email = modelli_email.messaggio_da("O", "C", {}, aziende[0], ["c@x.it"], from_email="altro@zenpark.it")
    assert email.from_email == "altro@zenpark.it"


def test_chatter_dal_mittente_dell_azienda(aziende, settings):
    settings.SITO_URL = "https://hub.example.com"
    zen, senza = aziende
    autore = User.objects.create_user("anna", "anna@example.com", "x")
    bruno = User.objects.create_user("bruno", "bruno@example.com", "x")
    for az in (zen, senza):
        chatter.segui(az, bruno)
        chatter.scrivi(az, autore, "Ciao")
    assert [e.from_email for e in mail.outbox] == ["Zen Park <offerte@zenpark.it>", "noreply@hub.example.it"]


def test_scheda_azienda_mostra_i_campi(admin_client, aziende):
    html = admin_client.get(f"/core/aziende/{aziende[0].pk}/modifica/").content.decode()
    assert "Email ai clienti" in html and 'name="email_mittente"' in html and 'name="email_mittente_nome"' in html
