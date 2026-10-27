import pytest
from django.contrib.auth.models import User
from django.core import mail

from core import chatter
from core.chatter import email as posta
from core.generici import ct_di
from core.models import Azienda, Lavoro


@pytest.fixture
def scena(db, settings):
    settings.SITO_URL = "https://hub.example.com"
    settings.EMAIL_RISPOSTE = "risposte@example.com"
    acme = Azienda.objects.create(nome="Acme")
    autore = User.objects.create_user("anna", "anna@example.com", "x", first_name="Anna")
    bruno = User.objects.create_user("bruno", "bruno@example.com", "x")
    senza = User.objects.create_user("senza", "", "x")
    spento = User.objects.create_user("spento", "spento@example.com", "x", is_active=False)
    for u in (bruno, senza, spento):
        chatter.segui(acme, u)
    return acme, autore, bruno


def test_messaggio_ai_follower(scena):
    acme, autore, bruno = scena
    m = chatter.scrivi(acme, autore, "Ciao a tutti")
    (email,) = mail.outbox
    assert email.to == ["bruno@example.com"] and email.subject.endswith("Acme")
    assert "Anna ha scritto" in email.body and "https://hub.example.com/core/aziende/" in email.body
    m.refresh_from_db()
    assert email.extra_headers["Message-ID"] == m.message_id and m.message_id.endswith("@hub.example.com>")
    ct = ct_di(acme).pk
    assert email.extra_headers["References"] == f"<rec-{ct}-{acme.pk}@hub.example.com>"
    (risposta,) = email.reply_to
    locale = risposta.split("@")[0]
    assert locale.startswith("risposte+") and posta.leggi_token(locale.split("+", 1)[1]) == (ct, acme.pk)
    assert email.alternatives[0][1] == "text/html"
    assert Lavoro.objects.get().funzione == "core.chatter.email.notifica"


def test_nota_e_tracciamento_non_partono(scena):
    acme, autore, _ = scena
    chatter.scrivi(acme, autore, "interna", tipo="nota")
    chatter.traccia(acme, {"nome": "Vecchio"}, autore)
    assert mail.outbox == [] and not Lavoro.objects.exists()


def test_autore_escluso_e_senza_destinatari(db):
    acme = Azienda.objects.create(nome="Solo")
    autore = User.objects.create_user("solo", "solo@example.com", "x")
    chatter.scrivi(acme, autore, "parlo da solo")         # l'autore diventa follower ma non riceve
    assert mail.outbox == [] and not Lavoro.objects.exists()


def test_senza_email_risposte_niente_reply_to(scena, settings):
    settings.EMAIL_RISPOSTE = ""
    acme, autore, _ = scena
    chatter.scrivi(acme, autore, "x")
    assert mail.outbox[0].reply_to == []


def test_token_falsificato():
    assert posta.leggi_token(posta.token_risposta(5, 9)) == (5, 9)
    vero = posta.token_risposta(5, 9)
    assert posta.leggi_token(vero.replace("-9-", "-8-")) is None
    assert posta.leggi_token("5-9-0000000000000000") is None
    assert posta.leggi_token("qualcosa") is None and posta.leggi_token("") is None
