from email.message import EmailMessage

import pytest
from django.contrib.auth.models import User
from django.core import mail

from core import chatter
from core.generici import ct_di
from core.chatter import entrata
from core.models import Azienda, EmailRicevuta, Messaggio
from core.viste import registry


@pytest.fixture(autouse=True)
def ambiente(settings, tmp_path, monkeypatch):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    settings.EMAIL_RISPOSTE = "risposte@example.com"
    vista = registry.per_modello(Azienda)
    monkeypatch.setattr(vista, "destinatari_esterni", lambda obj: [obj.email] if obj.email else [])
    entrata.svuota_gestori()
    yield
    entrata.svuota_gestori()


@pytest.fixture
def cliente(db):
    acme = Azienda.objects.create(nome="Acme", email="Cliente@Acme.it")
    interno = User.objects.create_user("anna", "anna@example.com", "x")
    chatter.segui(acme, interno)
    return acme, interno


def _email(da, mid, in_risposta=None, oggetto="Re: Acme", corpo="Grazie, ricevuto"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = da, "risposte@example.com", oggetto, mid
    if in_risposta:
        m["In-Reply-To"] = in_risposta
    m.set_content(corpo)
    return m.as_bytes()


def test_messaggio_anche_al_cliente_esterno(cliente):
    acme, interno = cliente
    supporto = User.objects.create_user("supporto", "supporto@example.com", "x")
    chatter.scrivi(acme, supporto, "Abbiamo preso in carico la richiesta")
    destinatari = sorted(e.to[0] for e in mail.outbox)
    assert destinatari == ["Cliente@Acme.it", "anna@example.com"]
    esterna = next(e for e in mail.outbox if e.to == ["Cliente@Acme.it"])
    assert "/core/aziende/" not in esterna.body and "continuare la conversazione" in esterna.body
    assert esterna.reply_to and esterna.reply_to[0].startswith("risposte+")


def test_nota_non_va_al_cliente(cliente):
    acme, interno = cliente
    chatter.scrivi(acme, interno, "interna", tipo="nota")
    assert mail.outbox == []


def test_risposta_del_cliente(cliente):
    acme, interno = cliente
    supporto = User.objects.create_user("supporto", "supporto@example.com", "x")
    m = chatter.scrivi(acme, supporto, "Domanda per il cliente")
    m.refresh_from_db()
    mail.outbox.clear()
    riga = entrata.ricevi(_email("Mario <cliente@acme.it>", "<c1@acme>", in_risposta=m.message_id))
    assert riga.stato == EmailRicevuta.ABBINATA
    risposta = riga.messaggio
    assert risposta.autore is None and risposta.autore_email == "cliente@acme.it" and risposta.corpo == "Grazie, ricevuto"
    assert sorted(e.to[0] for e in mail.outbox) == ["anna@example.com", "supporto@example.com"]   # non al cliente stesso


def test_esterno_non_ammesso(cliente):
    acme, _ = cliente
    m = chatter.scrivi(acme, None, "x", tipo="sistema")
    m.message_id = "<msg-x@hub>"
    m.save()
    assert entrata.ricevi(_email("altro@acme.it", "<c2@acme>", in_risposta=m.message_id)).stato == "rifiutata"


def test_gestore_delle_email_non_abbinate(db):
    def apri_azienda(msg, mittente):
        return Azienda.objects.create(nome=str(msg["Subject"]), email=mittente)
    entrata.registra_gestore(apri_azienda)
    riga = entrata.ricevi(_email("nuovo@cliente.it", "<n1@cliente>", oggetto="Nuova Srl", corpo="Vorrei informazioni"))
    nuova = Azienda.objects.get(nome="Nuova Srl")
    assert riga.stato == EmailRicevuta.ABBINATA and riga.messaggio.record == nuova
    assert riga.messaggio.autore_email == "nuovo@cliente.it"


def test_gestore_che_non_gestisce(db):
    entrata.registra_gestore(lambda msg, mittente: None)
    assert entrata.ricevi(_email("x@y.it", "<n2@y>")).stato == EmailRicevuta.NON_ABBINATA


def test_pannello_mostra_l_esterno(client, superuser, cliente):
    acme, _ = cliente
    Messaggio.objects.create(content_type_id=ct_di(acme).pk,
                             object_id=acme.pk, autore_email="cliente@acme.it", corpo="ciao")
    html = client.get(f"/core/aziende/{acme.pk}/").content.decode()
    assert "cliente@acme.it" in html and "esterno" in html
