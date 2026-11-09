import datetime

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from calendario import prenotazioni
from calendario.models import Evento, OrarioAppuntamento, Prenotazione, TipoAppuntamento
from contatti.models import Contatto
from core.models import Azienda


def _lunedi_prossimo():
    oggi = timezone.localdate()
    return oggi + datetime.timedelta(days=7 - oggi.weekday())


def _alle(giorno, ora, minuti=0):
    return timezone.make_aware(datetime.datetime.combine(giorno, datetime.time(ora, minuti)))


@pytest.fixture
def tipo(db):
    anna = User.objects.create_user("anna", "anna@example.com", "x")
    bruno = User.objects.create_user("bruno", "bruno@example.com", "x")
    t = TipoAppuntamento.objects.create(azienda=Azienda.objects.get(pk=1), nome="Consulenza", codice="consulenza",
                                        durata=30, pausa=0, preavviso=0, giorni_avanti=14, luogo="Sede")
    t.operatori.add(anna, bruno)
    OrarioAppuntamento.objects.create(tipo=t, giorno=0, dalle=datetime.time(9), alle=datetime.time(11))
    return t


def test_fasce_al_netto_degli_eventi(tipo):
    lun = _lunedi_prossimo()
    fasce = [f for f in prenotazioni.fasce(tipo) if timezone.localdate(f[0]) == lun]
    assert [timezone.localtime(i).strftime("%H:%M") for i, _ in fasce] == ["09:00", "09:30", "10:00", "10:30"]
    anna, bruno = tipo.operatori.order_by("username")
    for u in (anna, bruno):                                  # tutti e due occupati dalle 9 alle 10
        e = Evento.objects.create(azienda=tipo.azienda, titolo="Riunione", inizio=_alle(lun, 9), fine=_alle(lun, 10), organizzatore=u)
    e.partecipanti.add(anna)
    fasce = dict(f for f in prenotazioni.fasce(tipo) if timezone.localdate(f[0]) == lun)
    assert sorted(timezone.localtime(i).strftime("%H:%M") for i in fasce) == ["10:00", "10:30"]
    # nessuna fascia di domenica o oltre i giorni prenotabili
    assert all(timezone.localdate(i).weekday() == 0 for i, _ in prenotazioni.fasce(tipo))


def test_prenotazione_crea_evento_contatto_e_manda_conferma(tipo, settings):
    lun = _lunedi_prossimo()
    p = prenotazioni.prenota(tipo, _alle(lun, 9), "Mario Rossi", "mario@example.com", "333", "Rossi srl", "Vorrei info")
    assert p.evento.titolo == "Consulenza: Mario Rossi" and p.evento.contatti.get() == p.contatto
    assert p.contatto.email == "mario@example.com" and p.contatto.tipo == Contatto.PERSONA
    assert p.operatore in p.evento.partecipanti.all()
    # il secondo alla stessa ora va all'altro operatore, il terzo trova pieno
    q = prenotazioni.prenota(tipo, _alle(lun, 9), "Luca", "MARIO@example.com")
    assert q.operatore != p.operatore and q.contatto == p.contatto      # contatto ritrovato dall'email
    with pytest.raises(Exception, match="non è più libero"):
        prenotazioni.prenota(tipo, _alle(lun, 9), "Terzo", "t@example.com")
    with pytest.raises(Exception):
        prenotazioni.prenota(tipo, _alle(lun, 9, 15), "Fuori fascia", "f@example.com")
    mail.outbox.clear()
    prenotazioni.invia_conferma(p.pk)
    m = mail.outbox[0]
    assert m.to == ["mario@example.com"] and "confermato" in m.subject and "/calendario/prenotazione/" in m.body
    assert m.attachments[0][0] == "appuntamento.ics"


def test_opportunita_con_il_crm(tipo, settings):
    from django.apps import apps
    if not apps.is_installed("crm"):
        pytest.skip("CRM non installato")
    from crm.models import FaseCrm, Opportunita
    FaseCrm.objects.get_or_create(nome="Nuova", defaults={"ordine": 1})
    tipo.crea_opportunita = True
    tipo.save()
    p = prenotazioni.prenota(tipo, _alle(_lunedi_prossimo(), 10), "Gina", "gina@example.com", societa="Gina spa")
    o = Opportunita.objects.get(pk=p.opportunita_id)
    assert o.contatto == p.contatto and o.commerciale == p.operatore and "Prenotazione online" in o.origine


def test_pagina_pubblica_e_annullamento(client, tipo, settings):
    lun = _lunedi_prossimo()
    url = reverse("calendario:prenota", args=["consulenza"])
    r = client.get(url, {"giorno": lun.isoformat()})
    assert r.status_code == 200 and "09:30" in r.content.decode()
    inizio = timezone.localtime(_alle(lun, 9, 30)).isoformat()
    r = client.post(url, {"giorno": lun.isoformat(), "inizio": inizio, "nome": "Sara", "email": "sara@example.com"})
    assert "Prenotazione confermata" in r.content.decode()
    p = Prenotazione.objects.get(email="sara@example.com")
    # il robot che riempie il campo trappola non prenota
    client.post(url, {"inizio": inizio, "nome": "Bot", "email": "bot@example.com", "sito": "x"})
    assert not Prenotazione.objects.filter(email="bot@example.com").exists()
    link = prenotazioni.link(p)
    r = client.post(link.replace(settings.SITO_URL, ""), {"azione": "annulla", "motivo": "imprevisto"})
    p.refresh_from_db()
    assert p.stato == Prenotazione.ANNULLATA and p.evento is None and "annullato" in r.content.decode()
    assert any("annullato" in m.subject for m in mail.outbox)          # l'operatore è avvisato
    assert client.get("/calendario/prenotazione/falso/").status_code == 400
    # le pagine interne: tipo e prenotazione annullata
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    for interna in [f"/calendario/tipi-appuntamento/{tipo.pk}/", f"/calendario/prenotazioni/{p.pk}/", "/calendario/prenotazioni/"]:
        assert client.get(interna).status_code == 200, interna
    tipo.attivo = False
    tipo.save()
    assert client.get(url).status_code == 404


def test_promemoria_ai_clienti(tipo):
    lun = _lunedi_prossimo()
    p = prenotazioni.prenota(tipo, _alle(lun, 9), "Ugo", "ugo@example.com")
    mail.outbox.clear()
    assert prenotazioni.promemoria_clienti(adesso=_alle(lun, 9) - datetime.timedelta(days=2)) == 0
    assert prenotazioni.promemoria_clienti(adesso=_alle(lun, 9) - datetime.timedelta(hours=20)) == 1
    assert mail.outbox[0].to == ["ugo@example.com"] and "Promemoria" in mail.outbox[0].subject
    assert prenotazioni.promemoria_clienti(adesso=_alle(lun, 9) - datetime.timedelta(hours=19)) == 0
    p.refresh_from_db()
    assert p.promemoria_inviato


def test_annullata_da_noi_avvisa_il_cliente(tipo):
    p = prenotazioni.prenota(tipo, _alle(_lunedi_prossimo(), 10), "Ivo", "ivo@example.com")
    mail.outbox.clear()
    prenotazioni.annulla(p, da_cliente=False, motivo="operatore malato")
    destinatari = [m.to[0] for m in mail.outbox]
    assert "ivo@example.com" in destinatari
    cliente = next(m for m in mail.outbox if m.to == ["ivo@example.com"])
    assert "operatore malato" in cliente.body and cliente.attachments[0][0] == "annullato.ics"
