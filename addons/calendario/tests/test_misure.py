"""Misura aziendale del Calendario: gli appuntamenti, di default quelli dell'utente."""
import datetime

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from calendario.models import Evento
from core import misure
from core.models import Azienda
from core.viste.interroga import richiesta_di


def _evento(titolo, giorno, organizzatore=None, partecipanti=()):
    inizio = timezone.make_aware(datetime.datetime.combine(giorno, datetime.time(10)))
    e = Evento.objects.create(azienda=Azienda.objects.get(pk=1), titolo=titolo, inizio=inizio,
                              fine=inizio + datetime.timedelta(hours=1), organizzatore=organizzatore)
    e.partecipanti.set(partecipanti)
    return e


@pytest.fixture
def persone(db):
    return User.objects.create_superuser("anna", "anna@example.com", "x"), User.objects.create_user("bruno", "b@example.com", "x")


def test_appuntamenti_miei_e_tutti(persone):
    anna, bruno = persone
    oggi = timezone.localdate()
    _evento("Organizzo io", oggi, organizzatore=anna)
    _evento("Partecipo", oggi, organizzatore=bruno, partecipanti=[anna])
    _evento("Di Bruno", oggi, organizzatore=bruno)
    req = richiesta_di(anna)
    assert misure.calcola("calendario.appuntamenti", req, periodo="oggi")["valore"] == 2
    assert misure.calcola("calendario.appuntamenti", req, periodo="oggi", di="tutti")["valore"] == 3


def test_appuntamenti_domani(persone):
    anna, _ = persone
    oggi = timezone.localdate()
    _evento("Oggi", oggi, organizzatore=anna)
    _evento("Domani", oggi + datetime.timedelta(days=1), organizzatore=anna)
    assert misure.calcola("calendario.appuntamenti", richiesta_di(anna), periodo="domani")["valore"] == 1
