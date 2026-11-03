"""Riepilogo giornaliero: si apre da solo all'accesso, dice solo ciò che l'utente vede, e un modulo rotto non lo ferma."""
import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.test import RequestFactory
from django.utils import timezone

import fiscale
import helpdesk
from calendario.models import Evento
from contatti.models import Contatto
from core.models import Azienda, ProfiloUtente
from fatturazione.models import Fattura, Scadenza
from helpdesk.models import FaseTicket, Ticket
from riepilogo import accessi, motore
from riepilogo.models import Preferenza
from todo.models import Attivita
from vendite.models import OrdineVendita


def _con_azienda(modello, azienda):
    return {"azienda": azienda} if any(f.name == "azienda" for f in modello._meta.fields) else {}


@pytest.fixture
def scena(db):
    for app in (fiscale, helpdesk):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    root = User.objects.create_superuser("root", "r@example.com", "x", first_name="Anna")
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, partita_iva="12345678903")
    return {"az": azienda, "root": root, "cliente": cliente, "oggi": timezone.localdate()}


def _richiesta(utente, azienda):
    richiesta = RequestFactory().get("/")
    richiesta.user, richiesta.azienda, richiesta.session = utente, azienda, {}
    return richiesta


def _dati(s, utente):
    oggi = s["oggi"]
    OrdineVendita.objects.create(azienda=s["az"], cliente=s["cliente"], numero="PV/1", numero_ordine="OV/1", stato=OrdineVendita.CONFERMATO, confermato_il=oggi, totale=D(100))
    f = Fattura.objects.create(azienda=s["az"], cliente=s["cliente"], stato=Fattura.EMESSA, numero="1/2026", totale=D(122))
    Scadenza.objects.create(fattura=f, data=oggi - datetime.timedelta(days=1), importo=D(122))
    t = Ticket.objects.create(azienda=s["az"], oggetto="Server giù", fase=FaseTicket.objects.filter(chiusa=False).first())
    Ticket.objects.filter(pk=t.pk).update(scadenza_sla=timezone.now() - datetime.timedelta(hours=1))
    Attivita.objects.create(titolo="Chiama Rossi", assegnatario=utente, scadenza=oggi, **_con_azienda(Attivita, s["az"]))
    inizio = timezone.make_aware(datetime.datetime.combine(oggi, datetime.time(10, 30)))
    Evento.objects.create(titolo="Riunione di avvio", inizio=inizio, fine=inizio + datetime.timedelta(hours=1), organizzatore=utente, **_con_azienda(Evento, s["az"]))


def test_accesso_registra_e_apre_una_volta(scena, client):
    client.force_login(scena["root"])
    p = Preferenza.objects.get(utente=scena["root"])
    assert p.ultimo_accesso and p.accesso_precedente is None and client.session[accessi.CHIAVE_SESSIONE]
    html = client.get("/dashboard/").content.decode()
    assert 'hx-trigger="load"' in html and "apertura=login" in html and 'id="rp-icona"' in html
    r = client.get("/riepilogo/pannello/?apertura=login")
    assert r.status_code == 200 and "Buon" in r.content.decode() and "primo accesso" in r.content.decode()
    assert accessi.CHIAVE_SESSIONE not in client.session
    assert "apertura=login" not in client.get("/dashboard/").content.decode()
    client.force_login(scena["root"])
    p.refresh_from_db()
    assert p.accesso_precedente is not None and p.accesso_precedente < p.ultimo_accesso


def test_le_voci_dei_moduli_nelle_tre_sezioni(scena, client):
    _dati(scena, scena["root"])
    client.force_login(scena["root"])
    html = client.get("/riepilogo/").content.decode()
    for testo in ("ultimo accesso", "Oggi", "Da fare", "ordine confermato", "OV/1", "pagamento scaduto da incassare", "122,00 €",
                  "ticket con SLA scaduto", "Server giù", "ticket nuovo", "attività in scadenza oggi", "Chiama Rossi", "appuntamento oggi", "10:30 · Riunione di avvio"):
        assert testo in html, testo
    assert "is-urgente" in html and "Buongiorno, Anna" in html or "Buon pomeriggio, Anna" in html or "Buonasera, Anna" in html
    richiesta = _richiesta(scena["root"], scena["az"])
    dati = motore.calcola(richiesta, timezone.now() - datetime.timedelta(days=1), rigoroso=True)       # ogni modulo: nessuno deve rompersi
    assert [s["codice"] for s in dati["sezioni"]] == ["novita", "oggi", "attenzione"] and dati["urgenti"] >= 2
    attenzione = next(s for s in dati["sezioni"] if s["codice"] == "attenzione")
    assert all(v["urgente"] for v in attenzione["voci"][:2])                 # prima le urgenti


def test_solo_cio_che_l_utente_puo_vedere(scena, client):
    anna = User.objects.create_user("anna", "a@example.com", "x")
    profilo, _ = ProfiloUtente.objects.get_or_create(utente=anna)
    profilo.azienda_predefinita = scena["az"]
    profilo.save()
    profilo.aziende.add(scena["az"])
    anna.user_permissions.add(*Permission.objects.filter(codename__in=("view_preferenza", "view_attivita")))
    _dati(scena, anna)
    client.force_login(anna)
    html = client.get("/riepilogo/").content.decode()
    assert "Chiama Rossi" in html and "ticket" not in html.lower().split("<main", 1)[-1] and "OV/1" not in html
    senza = User.objects.create_user("bruno", "b@example.com", "x")
    client.force_login(senza)
    assert client.get("/riepilogo/").status_code == 403 and client.get("/riepilogo/pannello/").status_code == 403
    assert 'id="rp-icona"' not in client.get("/dashboard/").content.decode()


def test_un_modulo_con_errore_non_ferma_gli_altri(scena, monkeypatch):
    _dati(scena, scena["root"])
    vero = motore.risolvi

    def finto(percorso):
        return (lambda *a, **k: 1 / 0) if percorso.startswith("vendite.") else vero(percorso)
    monkeypatch.setattr(motore, "risolvi", finto)
    richiesta = _richiesta(scena["root"], scena["az"])
    dal = timezone.now() - datetime.timedelta(days=1)
    dati = motore.calcola(richiesta, dal)
    assert dati["totale"] >= 4 and not any("ordine" in v["etichetta"] for s in dati["sezioni"] for v in s["voci"])
    with pytest.raises(ZeroDivisionError):
        motore.calcola(richiesta, dal, rigoroso=True)


def test_da_quando(scena):
    adesso = timezone.now()
    p = Preferenza(utente=scena["root"], accesso_precedente=adesso - datetime.timedelta(days=3))
    dal, testo = motore.da_quando(p, "accesso", adesso)
    assert dal == p.accesso_precedente and testo.startswith("dal tuo ultimo accesso")
    p.accesso_precedente = adesso - datetime.timedelta(days=90)
    dal, testo = motore.da_quando(p, "accesso", adesso)
    assert dal == adesso - datetime.timedelta(days=30) and "al massimo 30 giorni" in testo
    dal, testo = motore.da_quando(p, "settimana", adesso)
    assert testo == "dagli ultimi 7 giorni" and timezone.localtime(dal).hour == 0 and (timezone.localtime(adesso).date() - timezone.localtime(dal).date()).days == 7
    dal, testo = motore.da_quando(Preferenza(utente=scena["root"]), "accesso", adesso)
    assert "primo accesso" in testo and (timezone.localtime(adesso).date() - timezone.localtime(dal).date()).days == 1


def test_preferenza_ed_esterni(scena, client):
    client.force_login(scena["root"])
    assert client.post("/riepilogo/preferenza/", {"mostra": "0"}).status_code == 204
    assert not Preferenza.objects.get(utente=scena["root"]).mostra_al_login
    client.force_login(scena["root"])
    assert accessi.CHIAVE_SESSIONE not in client.session
    esterno = User.objects.create_user("cliente", "c@example.com", "x")
    profilo, _ = ProfiloUtente.objects.get_or_create(utente=esterno)
    profilo.esterno = True
    profilo.save()
    client.force_login(User.objects.get(pk=esterno.pk))        # come al login vero: l'utente si ricarica dal database
    assert not Preferenza.objects.filter(utente=esterno).exists() and accessi.CHIAVE_SESSIONE not in client.session


def test_senza_niente_e_saluto(scena, client):
    client.force_login(scena["root"])
    assert "Niente di nuovo e niente in sospeso" in client.get("/riepilogo/").content.decode()
    giorno = datetime.datetime(2026, 11, 3, 9, 0, tzinfo=datetime.timezone.utc)
    assert motore.saluto(scena["root"], giorno) == "Buongiorno, Anna"
    assert motore.saluto(scena["root"], giorno.replace(hour=14)).startswith("Buon pomeriggio")
    assert motore.saluto(scena["root"], giorno.replace(hour=19)).startswith("Buonasera")
