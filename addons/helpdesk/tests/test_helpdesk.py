import datetime
from email.message import EmailMessage
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

import helpdesk
from contatti.models import Contatto
from core import chatter, parametri
from core.chatter import email as posta
from core.chatter import entrata
from core.models import Azienda
from core.registry import manifest
from core.registry.groups import crea_gruppi
from helpdesk import lavori
from helpdesk.models import FaseTicket, Team, Ticket

CARTELLA = Path(helpdesk.__file__).parent


@pytest.fixture(autouse=True)
def ambiente(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    settings.EMAIL_RISPOSTE = "risposte@example.com"


@pytest.fixture
def dati(db):
    call_command("loaddata", str(CARTELLA / "data" / "iniziali.json"), verbosity=0)
    crea_gruppi(manifest.leggi(CARTELLA))


@pytest.fixture
def operatore(dati, client):
    u = User.objects.create_user("olga", "olga@example.com", "x")
    u.groups.add(Group.objects.get(name="Helpdesk / Operatore"))
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    return u


def _ticket(**kw):
    return Ticket.objects.create(azienda=Azienda.objects.get(pk=1), **{"oggetto": "Problema", **kw})


def test_numero_e_sla(dati):
    t = _ticket(priorita="urgente")
    assert t.numero == f"TK/{timezone.localdate().year}/00001"
    assert abs((t.scadenza_sla - t.creato) - datetime.timedelta(hours=4)) < datetime.timedelta(seconds=5)
    parametri.scrivi("helpdesk.ore_bassa", 100, azienda=t.azienda)
    t.priorita = "bassa"
    t.save()
    assert abs((t.scadenza_sla - t.creato) - datetime.timedelta(hours=100)) < datetime.timedelta(seconds=5)


def test_chiusura(dati):
    t = _ticket()
    t.fase = FaseTicket.objects.get(chiusa=True)
    t.save(update_fields=["fase"])
    t.refresh_from_db()
    assert t.chiuso_il is not None
    t.fase = FaseTicket.objects.get(nome="In lavorazione")
    t.save()
    assert t.chiuso_il is None


def test_bottoni(client, operatore):
    t = _ticket()
    client.post(f"/helpdesk/ticket/{t.pk}/bottone/prendi_in_carico/")
    t.refresh_from_db()
    assert t.assegnatario == operatore and t.fase.nome == "In lavorazione" and chatter.segue(t, operatore)
    client.post(f"/helpdesk/ticket/{t.pk}/bottone/risolvi/")
    t.refresh_from_db()
    assert t.fase.chiusa and t.chiuso_il


def test_messaggi_al_cliente_e_risposta(client, operatore):
    t = _ticket(email_cliente="cliente@acme.it")
    m = chatter.scrivi(t, operatore, "Stiamo verificando")
    (email,) = mail.outbox
    assert email.to == ["cliente@acme.it"]
    m.refresh_from_db()
    risposta = EmailMessage()
    risposta["From"], risposta["To"], risposta["Subject"] = "cliente@acme.it", "risposte@example.com", "Re"
    risposta["Message-ID"], risposta["In-Reply-To"] = "<r1@acme>", m.message_id
    risposta.set_content("Grazie, ora funziona")
    riga = entrata.ricevi(risposta.as_bytes())
    assert riga.stato == "abbinata" and riga.messaggio.autore_email == "cliente@acme.it"


def test_ticket_da_email_solo_all_indirizzo_helpdesk(dati):
    Team.objects.get(pk=1).membri.add(User.objects.create_user("t1", "t1@example.com", "x"))
    acme = Contatto.objects.create(azienda=Azienda.objects.get(pk=1), nome="Acme", email="Info@Acme.it")

    def email(a, mid):
        e = EmailMessage()
        e["From"], e["To"], e["Subject"], e["Message-ID"] = "info@acme.it", a, "Stampante bloccata", mid
        e.set_content("La stampante non stampa da stamattina")
        return e.as_bytes()
    assert entrata.ricevi(email("assistenza@example.com", "<e0@acme>")).stato == "non_abbinata"   # parametro vuoto
    parametri.scrivi("helpdesk.indirizzo_helpdesk", "assistenza@example.com")
    riga = entrata.ricevi(email("Assistenza <assistenza@example.com>", "<e1@acme>"))
    t = Ticket.objects.get(oggetto="Stampante bloccata")
    assert riga.stato == "abbinata" and riga.messaggio.record == t
    assert t.contatto == acme and t.email_cliente == "info@acme.it" and t.team_id == 1
    assert chatter.messaggi_di(t).first().corpo == "La stampante non stampa da stamattina"
    assert "t1@example.com" in [m.to[0] for m in mail.outbox]          # il team segue il ticket


def test_avvisi_sla(dati):
    olga = User.objects.create_user("o2", "o2@example.com", "x")
    t = _ticket(assegnatario=olga, priorita="urgente")
    Ticket.objects.filter(pk=t.pk).update(scadenza_sla=timezone.now() + datetime.timedelta(minutes=30))
    _ticket(assegnatario=olga, priorita="bassa")
    assert lavori.avvisi_sla() == 1 and lavori.avvisi_sla() == 0
    assert "in scadenza" in mail.outbox[0].subject


def test_viste_e_sla_in_lista(client, operatore):
    t = _ticket()
    Ticket.objects.filter(pk=t.pk).update(scadenza_sla=timezone.now() - datetime.timedelta(hours=1))
    assert "scaduto" in client.get("/helpdesk/ticket/").content.decode()
    for url in ("/helpdesk/ticket/kanban/", "/helpdesk/ticket/grafico/", f"/helpdesk/ticket/{t.pk}/"):
        assert client.get(url).status_code == 200, url


def test_post_install_numera_i_demo(dati):
    call_command("loaddata", str(CARTELLA / "data" / "demo.json"), verbosity=0)
    from helpdesk import hooks
    hooks.post_install(None)
    assert not Ticket.objects.filter(numero="").exists() and not Ticket.objects.filter(scadenza_sla=None).exists()
    assert Ticket.objects.get(oggetto="Aggiornamento completato?").chiuso_il is not None
