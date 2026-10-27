import datetime
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core import mail
from django.utils import timezone

import calendario
from calendario import lavori
from calendario.ics import ics
from calendario.models import Evento
from core.models import Azienda
from core.registry import manifest
from core.registry.groups import crea_gruppi

CARTELLA = Path(calendario.__file__).parent


def _quando(giorni=1, ora=10):
    return timezone.make_aware(datetime.datetime.combine(timezone.localdate() + datetime.timedelta(days=giorni),
                                                         datetime.time(ora)))


def _utente(nome):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.title())
    u.groups.add(Group.objects.get(name="Calendario / Utente"))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def persone(db):
    crea_gruppi(manifest.leggi(CARTELLA))
    return _utente("anna"), _utente("bruno"), _utente("carlo")


@pytest.fixture
def prima(db):
    return Azienda.objects.get(pk=1)


def test_crea_con_invito(client, persone):
    anna, bruno, _ = persone
    client.force_login(anna)
    r = client.post("/calendario/eventi/nuovo/", {
        "titolo": "Riunione budget", "inizio": _quando().strftime("%Y-%m-%d %H:%M"),
        "fine": _quando(ora=11).strftime("%Y-%m-%d %H:%M"), "partecipanti": [bruno.pk], "promemoria": "15"})
    assert r.status_code == 302
    e = Evento.objects.get(titolo="Riunione budget")
    assert e.organizzatore == anna
    (invito,) = mail.outbox
    assert invito.to == ["bruno@example.com"] and invito.attachments[0][0] == "invito.ics"
    assert "METHOD:REQUEST" in invito.attachments[0][1]


def test_fine_prima_dell_inizio(client, persone):
    client.force_login(persone[0])
    r = client.post("/calendario/eventi/nuovo/", {"titolo": "X", "inizio": _quando(ora=11).strftime("%Y-%m-%d %H:%M"),
                                                  "fine": _quando(ora=10).strftime("%Y-%m-%d %H:%M"), "promemoria": "0"})
    assert r.status_code == 200 and "non può precedere" in r.content.decode()


def test_eventi_privati(client, persone, prima):
    anna, bruno, carlo = persone
    privato = Evento.objects.create(azienda=prima, titolo="Colloquio riservato", inizio=_quando(), fine=_quando(ora=11),
                                    organizzatore=anna, privato=True)
    privato.partecipanti.add(bruno)
    Evento.objects.create(azienda=prima, titolo="Pubblico", inizio=_quando(), fine=_quando(ora=11))
    for u, vede in [(anna, True), (bruno, True), (carlo, False)]:
        client.force_login(u)
        titoli = [o.titolo for o, _ in client.get("/calendario/eventi/").context["righe"]]
        assert ("Colloquio riservato" in titoli) is vede and "Pubblico" in titoli
        assert client.get(f"/calendario/eventi/{privato.pk}/").status_code == (200 if vede else 404)


def test_ics(persone, prima):
    anna, bruno, _ = persone
    e = Evento.objects.create(azienda=prima, titolo="Pranzo, con tutti; anche lunghissimo " * 4, luogo="Bar",
                              inizio=_quando(), fine=_quando(ora=11), organizzatore=anna)
    e.partecipanti.add(bruno)
    testo = ics(e)
    assert testo.startswith("BEGIN:VCALENDAR") and "DTSTART:" in testo and "mailto:bruno@example.com" in testo
    assert "\\," in testo and all(len(r.encode()) <= 75 for r in testo.split("\r\n"))
    e.tutto_il_giorno = True
    assert "DTSTART;VALUE=DATE:" in ics(e)


def test_bottone_ics(client, persone, prima):
    e = Evento.objects.create(azienda=prima, titolo="Scaricabile", inizio=_quando(), fine=_quando(ora=11))
    client.force_login(persone[2])
    r = client.post(f"/calendario/eventi/{e.pk}/bottone/scarica_ics/")
    assert r["Content-Type"].startswith("text/calendar") and b"SUMMARY:Scaricabile" in r.content


def test_promemoria(persone, prima):
    anna, bruno, _ = persone
    vicino = Evento.objects.create(azienda=prima, titolo="Tra poco", inizio=timezone.now() + datetime.timedelta(minutes=10),
                                   fine=timezone.now() + datetime.timedelta(minutes=70), organizzatore=anna, promemoria=15)
    vicino.partecipanti.add(bruno)
    Evento.objects.create(azienda=prima, titolo="Domani", inizio=_quando(giorni=2), fine=_quando(giorni=2, ora=11),
                          promemoria=60)
    assert lavori.promemoria() == 1
    assert sorted(m.to[0] for m in mail.outbox) == ["anna@example.com", "bruno@example.com"]
    assert lavori.promemoria() == 0                                     # una volta sola


def test_calendario_e_manifest(client, persone, prima):
    Evento.objects.create(azienda=prima, titolo="In calendario", inizio=_quando(), fine=_quando(ora=11))
    client.force_login(persone[0])
    assert client.get("/calendario/eventi/calendario/").status_code == 200
    m = manifest.leggi(CARTELLA)
    assert m.depends == ["contatti"] and m.cron[0]["ogni"] == "5m"
