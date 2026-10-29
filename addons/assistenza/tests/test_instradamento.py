import datetime
from email.message import EmailMessage

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from assistenza import instradamento, sla
from assistenza.models import Contratto, DatiTicket, PoliticaSLA, Supporto
from contatti.models import Contatto
from core import chatter, parametri
from core.models import Azienda
from helpdesk.models import Team, Ticket
from progetti.models import Progetto


def _ora(*a):
    return timezone.make_aware(datetime.datetime(*a))


@pytest.fixture
def scena(db):
    import helpdesk
    from pathlib import Path

    from django.core.management import call_command
    call_command("loaddata", str(Path(helpdesk.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    luca, sara, piero = (User.objects.create_user(n, f"{n}@example.com", "x") for n in ("luca", "sara", "piero"))
    team = Team.objects.create(nome="Sviluppo gestionale")
    team.membri.add(luca, sara)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", email="it@rossi.it", cliente=True)
    referente = Contatto.objects.create(azienda=azienda, nome="Anna Rossi", tipo="persona", societa=cliente,
                                        email="anna@rossi.it")
    progetto = Progetto.objects.create(azienda=azienda, nome="Gestionale Rossi", cliente=cliente, responsabile=piero)
    politica = PoliticaSLA.objects.create(nome="Premium", ore_lavorative=False, risposta_media=2, risoluzione_media=10,
                                          risposta_alta=1, risoluzione_alta=4)
    contratto = Contratto.objects.create(azienda=azienda, nome="Premium 2026", cliente=cliente, politica=politica,
                                         inizio=datetime.date(2026, 1, 1))
    supporto = Supporto.objects.create(azienda=azienda, progetto=progetto, team=team, responsabile=sara)
    return {"azienda": azienda, "luca": luca, "sara": sara, "team": team, "cliente": cliente, "referente": referente,
            "progetto": progetto, "contratto": contratto, "supporto": supporto, "politica": politica}


def test_ore_lavorative():
    politica = PoliticaSLA(nome="x", inizio_giornata=datetime.time(9), fine_giornata=datetime.time(18))
    assert sla.aggiungi_ore(_ora(2026, 10, 30, 17), 2, politica) == _ora(2026, 11, 2, 10)      # venerdì → lunedì
    assert sla.aggiungi_ore(_ora(2026, 10, 31, 12), 1, politica) == _ora(2026, 11, 2, 10)      # sabato → lunedì
    assert sla.aggiungi_ore(_ora(2026, 10, 29, 7), 9, politica) == _ora(2026, 10, 29, 18)      # prima dell'apertura
    assert sla.aggiungi_ore(_ora(2026, 10, 29, 10), 20, politica) == _ora(2026, 11, 2, 12)      # gio 8 + ven 9 + lun 3
    politica.ore_lavorative = False
    assert sla.aggiungi_ore(_ora(2026, 10, 30, 17), 2, politica) == _ora(2026, 10, 30, 19)


def test_contratto_valido(scena):
    assert Contratto.valido_per(scena["referente"]) == scena["contratto"]                     # la persona dell'azienda
    Contratto.objects.filter(pk=scena["contratto"].pk).update(fine=datetime.date(2026, 6, 30))
    assert Contratto.valido_per(scena["cliente"], datetime.date(2026, 10, 1)) is None
    assert Contratto.valido_per(None) is None


def test_ticket_del_progetto_al_suo_team_con_le_scadenze_del_contratto(scena):
    ticket = Ticket.objects.create(azienda=scena["azienda"], oggetto="Errore nel salvataggio",
                                   contatto=scena["referente"])
    ticket.refresh_from_db()
    dati = DatiTicket.objects.get(ticket=ticket)
    assert dati.progetto == scena["progetto"]                                       # l'unico progetto del cliente
    assert ticket.team == scena["team"] and ticket.assegnatario == scena["sara"]
    assert ticket.scadenza_sla == ticket.creato + datetime.timedelta(hours=10)      # contratto Premium, 24 ore
    assert dati.scadenza_risposta == ticket.creato + datetime.timedelta(hours=2)
    assert set(chatter.follower_di(ticket)) >= {scena["luca"], scena["sara"]}
    ticket.priorita = Ticket.ALTA
    ticket.save()
    ticket.refresh_from_db()
    assert ticket.scadenza_sla == ticket.creato + datetime.timedelta(hours=4)


def test_senza_responsabile_il_meno_carico(scena):
    Supporto.objects.filter(pk=scena["supporto"].pk).update(responsabile=None)
    Ticket.objects.create(azienda=scena["azienda"], oggetto="Vecchio", assegnatario=scena["luca"])
    ticket = Ticket.objects.create(azienda=scena["azienda"], oggetto="Nuovo", contatto=scena["cliente"])
    ticket.refresh_from_db()
    assert ticket.assegnatario == scena["sara"]                                       # luca ne ha già uno aperto


def test_senza_progetto_unico_niente_instradamento(scena):
    Progetto.objects.create(azienda=scena["azienda"], nome="App mobile", cliente=scena["cliente"])
    altro = Supporto.objects.create(azienda=scena["azienda"], progetto=Progetto.objects.get(nome="App mobile"))
    ticket = Ticket.objects.create(azienda=scena["azienda"], oggetto="Quale?", contatto=scena["cliente"])
    ticket.refresh_from_db()
    assert DatiTicket.objects.get(ticket=ticket).progetto is None and ticket.team is None
    instradamento.instrada(ticket, progetto=altro.progetto, forza=True)
    assert DatiTicket.objects.get(ticket=ticket).progetto == altro.progetto


def test_scelte_manuali_non_si_toccano(scena):
    ticket = Ticket.objects.create(azienda=scena["azienda"], oggetto="Già assegnato", contatto=scena["cliente"],
                                   assegnatario=scena["luca"])
    ticket.refresh_from_db()
    assert ticket.assegnatario == scena["luca"]


def test_ticket_da_email_al_progetto(scena):
    from helpdesk.email import apri_ticket
    parametri.scrivi("helpdesk.indirizzo_helpdesk", "assistenza@noi.it")
    Team.objects.create(nome="Aaa primo team")
    msg = EmailMessage()
    msg["Subject"], msg["To"], msg["From"] = "Non funziona la stampa", "assistenza@noi.it", "anna@rossi.it"
    ticket = apri_ticket(msg, "anna@rossi.it")
    ticket.refresh_from_db()
    assert ticket.team == scena["team"] and DatiTicket.objects.get(ticket=ticket).canale == "email"


def test_prima_risposta(scena):
    ticket = Ticket.objects.create(azienda=scena["azienda"], oggetto="Domanda", contatto=scena["cliente"])
    chatter.scrivi(ticket, scena["sara"], "Nota interna", tipo="nota")
    assert DatiTicket.objects.get(ticket=ticket).risposta_il is None
    chatter.scrivi(ticket, scena["sara"], "Ciao, ci guardiamo subito.")
    assert DatiTicket.objects.get(ticket=ticket).risposta_il is not None


def test_schede_su_ticket_e_progetto(client, scena):
    client.force_login(User.objects.create_superuser("root", "r@example.com", "x"))
    ticket = Ticket.objects.create(azienda=scena["azienda"], oggetto="Scheda", contatto=scena["cliente"])
    html = client.get(f"/helpdesk/ticket/{ticket.pk}/").content.decode()
    assert "Assistenza" in html and "Gestionale Rossi" in html and "Prima risposta entro" in html
    html = client.get(f"/progetti/progetti/{scena['progetto'].pk}/").content.decode()
    assert "Assistenza clienti" in html and "Sviluppo gestionale" in html


def test_segnali_fermi_senza_tabelle_o_con_modulo_disattivato(db, monkeypatch):
    from assistenza import segnali
    from core.models import Modulo
    monkeypatch.setattr(segnali, "_pronte", False)
    monkeypatch.setattr(segnali.connection.introspection, "table_names", lambda *a, **k: [])
    assert not segnali.attiva()                                     # migrazioni non ancora applicate
    monkeypatch.undo()
    assert segnali.attiva()
    Modulo.objects.update_or_create(slug="assistenza", defaults={"nome": "Assistenza", "disattivato": True})
    assert not segnali.attiva()
