"""Valutazione del cliente alla chiusura e guida online."""
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command

import helpdesk
from contatti.models import Contatto
from core import parametri
from core.models import Azienda, Messaggio, TipoAttivita
from helpdesk import lavori
from helpdesk.models import Articolo, FaseTicket, Team, Ticket, Valutazione


@pytest.fixture
def scena(db):
    call_command("loaddata", str(Path(helpdesk.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    return azienda, FaseTicket.objects.filter(chiusa=True).first()


def _chiuso(azienda, chiusa, **extra):
    t = Ticket.objects.create(azienda=azienda, oggetto="Stampa", email_cliente="c@rossi.it", **extra)
    t.fase = chiusa
    t.save()
    return t


def _link():
    testo = [m for m in mail.outbox if "Com'è andata" in m.subject][-1].body
    return "/" + testo.split("://")[1].split("/", 1)[1].split()[0]


def test_chiusura_manda_il_link_una_volta(client, scena):
    azienda, chiusa = scena
    t = _chiuso(azienda, chiusa)
    assert len([m for m in mail.outbox if "Com'è andata" in m.subject]) == 1
    t.oggetto = "Altro"
    t.save()
    assert len([m for m in mail.outbox if "Com'è andata" in m.subject]) == 1
    assert b"hd-scelta-stelle" in client.get(_link()).content


def test_senza_email_o_con_parametro_spento_niente_invito(scena):
    azienda, chiusa = scena
    t = Ticket.objects.create(azienda=azienda, oggetto="Senza email")
    t.fase = chiusa
    t.save()
    parametri.scrivi("helpdesk.chiedi_valutazione", False, azienda)
    _chiuso(azienda, chiusa)
    assert not [m for m in mail.outbox if "Com'è andata" in m.subject]


def test_voto_buono_e_correzione(client, scena):
    azienda, chiusa = scena
    t = _chiuso(azienda, chiusa)
    link = _link()
    assert client.post(link, {"voto": "9"}).status_code == 200 and not Valutazione.objects.exists()
    assert b"Grazie" in client.post(link, {"voto": "5", "commento": "Veloci"}).content
    assert Valutazione.objects.get(ticket=t).stelle == "★★★★★"
    client.post(link, {"voto": "4"})
    assert Valutazione.objects.get(ticket=t).voto == 4


def test_voto_basso_avvisa_chi_ha_seguito(client, scena):
    azienda, chiusa = scena
    TipoAttivita.objects.get_or_create(nome="Da fare")
    anna = User.objects.create_user("anna", "a@example.com", "x")
    t = _chiuso(azienda, chiusa, assegnatario=anna)
    client.post(_link(), {"voto": "1", "commento": "Lenti"})
    from core import attivita
    voci = list(attivita.di(t))
    assert voci[0].assegnatario == anna and "1/5" in voci[0].riepilogo
    assert Messaggio.objects.filter(tipo=Messaggio.NOTA, corpo__contains="Lenti").exists()


def test_link_manomesso(client, scena):
    assert client.get("/helpdesk/valuta/falso/").status_code == 400


def test_media_nel_team_e_nel_ticket(client, superuser, scena):
    azienda, chiusa = scena
    team = Team.objects.create(nome="Supporto")
    t = _chiuso(azienda, chiusa, team=team)
    Valutazione.objects.create(ticket=t, voto=4)
    assert "4.0 ★" in client.get("/helpdesk/team/").content.decode()
    assert "Giudizio del cliente" in client.get(f"/helpdesk/ticket/{t.pk}/").content.decode()
    assert client.get("/helpdesk/valutazioni/").status_code == 200
    assert client.get(f"/helpdesk/valutazioni/{t.valutazione.pk}/modifica/").status_code in (403, 404)


def _articolo(azienda, titolo="Come stampare una fattura", **extra):
    return Articolo.objects.create(azienda=azienda, titolo=titolo, corpo="Apri la fattura e premi stampa.",
                                   **{"pubblicato": True, "pubblico": True, **extra})


def test_guida_pubblica_solo_gli_articoli_online(client, scena):
    azienda, _ = scena
    online = _articolo(azienda)
    bozza = _articolo(azienda, "Bozza segreta", pubblicato=False)
    clienti = _articolo(azienda, "Solo clienti", pubblico=False)
    pagina = client.get("/helpdesk/guida/").content.decode()
    assert online.titolo in pagina and bozza.titolo not in pagina and clienti.titolo not in pagina
    assert client.get(f"/helpdesk/guida/{bozza.pk}/").status_code == 404
    assert client.get(f"/helpdesk/guida/{clienti.pk}/").status_code == 404
    assert client.get(f"/helpdesk/guida/{online.pk}/").status_code == 200
    online.refresh_from_db()
    assert online.visite == 1


def test_ricerca_per_parole(client, scena):
    azienda, _ = scena
    _articolo(azienda)
    _articolo(azienda, "Cambiare la password")
    risposta = client.get("/helpdesk/guida/cerca/", {"q": "non riesco a stampare la fattura"}).json()
    assert [a["titolo"] for a in risposta["articoli"]][0] == "Come stampare una fattura"
    assert "Cambiare" not in client.get("/helpdesk/guida/", {"q": "stampare"}).content.decode()


def test_utile_conta_una_volta_per_sessione(client, scena):
    azienda, _ = scena
    a = _articolo(azienda)
    client.post(f"/helpdesk/guida/{a.pk}/utile/", {"utile": "si"})
    client.post(f"/helpdesk/guida/{a.pk}/utile/", {"utile": "si"})
    a.refresh_from_db()
    assert a.utile_si == 1


def test_suggerimenti_sul_ticket(client, superuser, scena):
    azienda, _ = scena
    _articolo(azienda)
    t = Ticket.objects.create(azienda=azienda, oggetto="Non riesco a stampare")
    assert "Come stampare una fattura" in client.get(f"/helpdesk/ticket/{t.pk}/").content.decode()


def test_gestione_articoli(client, superuser, scena):
    assert client.get("/helpdesk/articoli/").status_code == 200
    r = client.post("/helpdesk/articoli/nuovo/", {"titolo": "Nuovo", "corpo": "Testo", "pubblicato": "on"})
    assert r.status_code == 302 and Articolo.objects.get().autore == superuser
