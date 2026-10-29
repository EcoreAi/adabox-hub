from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command

from assistenza.models import DatiTicket, Supporto
from contatti.models import Contatto
from core import chatter
from core.models import Azienda
from helpdesk.models import Team, Ticket
from progetti.models import Compito, FaseCompito, Progetto


@pytest.fixture
def scena(db, client):
    import helpdesk
    import progetti
    for app in (helpdesk, progetti):
        file = Path(app.__file__).parent / "data" / "iniziali.json"
        if file.exists():
            call_command("loaddata", str(file), verbosity=0)
    if not FaseCompito.objects.exists():
        FaseCompito.objects.create(nome="Da fare", ordine=10)
        FaseCompito.objects.create(nome="Fatto", ordine=90, chiusa=True)
    azienda = Azienda.objects.get(pk=1)
    sara = User.objects.create_superuser("sara", "sara@example.com", "x")
    client.force_login(sara)
    team = Team.objects.create(nome="Sviluppo")
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    progetto = Progetto.objects.create(azienda=azienda, nome="Gestionale Rossi", cliente=cliente)
    Supporto.objects.create(azienda=azienda, progetto=progetto, team=team, responsabile=sara)
    ticket = Ticket.objects.create(azienda=azienda, oggetto="La stampa si blocca", descrizione="Con 100 righe",
                                   contatto=cliente, email_cliente="anna@rossi.it", priorita=Ticket.URGENTE)
    DatiTicket.objects.filter(ticket=ticket).update(tecnici={"versione": "2.3.1", "ip": "1.2.3.4"})
    return {"sara": sara, "ticket": ticket, "progetto": progetto, "client": client}


def test_dal_ticket_al_compito_e_ritorno(scena):
    ticket, c = scena["ticket"], scena["client"]
    html = c.get(f"/helpdesk/ticket/{ticket.pk}/").content.decode()
    assert "Crea compito di sviluppo" in html
    c.post(f"/assistenza/ticket/{ticket.pk}/compito/")
    compito = Compito.objects.get()
    assert compito.progetto == scena["progetto"] and compito.titolo.startswith(f"[{ticket.numero}]")
    assert compito.priorita == Compito.ALTA and "versione: 2.3.1" in compito.descrizione
    assert "1.2.3.4" not in compito.descrizione and scena["sara"] in compito.assegnatari.all()
    c.post(f"/assistenza/ticket/{ticket.pk}/compito/")
    assert Compito.objects.count() == 1                                           # una volta sola
    mail.outbox.clear()
    compito.fase = FaseCompito.objects.filter(chiusa=True).first()
    compito.save()
    ticket.refresh_from_db()
    assert ticket.fase.chiusa
    avviso = chatter.messaggi_di(ticket).filter(tipo="messaggio").first()
    assert "la correzione per «La stampa si blocca» è pronta" in avviso.corpo
    compito.save()                                                                  # già chiuso: niente doppioni
    assert chatter.messaggi_di(ticket).filter(tipo="messaggio", corpo__contains="correzione").count() == 1


def test_senza_progetto_niente_compito(scena):
    ticket = Ticket.objects.create(azienda=scena["ticket"].azienda, oggetto="Senza progetto")
    r = scena["client"].post(f"/assistenza/ticket/{ticket.pk}/compito/", follow=True)
    assert "non è collegato a un progetto" in r.content.decode() and not Compito.objects.exists()


def test_avviso_al_cliente_quando_esce_la_versione(scena):
    from progetti.models import Rilascio, TipoCompito
    TipoCompito.objects.get_or_create(nome="Bug", defaults={"difetto": True})
    ticket, c = scena["ticket"], scena["client"]
    c.post(f"/assistenza/ticket/{ticket.pk}/compito/")
    compito = Compito.objects.get()
    assert compito.tipo.difetto                                                     # il bug resta un bug
    rilascio = Rilascio.objects.create(azienda=compito.azienda, progetto=compito.progetto, versione="2.4.0")
    compito.rilascio = rilascio
    compito.fase = FaseCompito.objects.filter(chiusa=True).first()
    compito.save()
    pronta = chatter.messaggi_di(ticket).filter(tipo="messaggio").first()
    assert "disponibile con la versione 2.4.0" in pronta.corpo
    rilascio.rilascia(scena["sara"])
    uscita = chatter.messaggi_di(ticket).filter(tipo="messaggio", corpo__contains="è disponibile").get()
    assert "La versione 2.4.0 di Gestionale Rossi è disponibile" in uscita.corpo
