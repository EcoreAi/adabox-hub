"""Controlli qualità: merce in quarantena al ricevimento (non spedibile), superato la libera, respinto apre la non
conformità del fornitore; controllo obbligatorio prima della spedizione."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from core import parametri
from magazzino import operazioni, qualita_merce
from magazzino.models import (Consegna, ControlloQualita, NonConformita, PuntoControllo, Ricevimento, RigaConsegna, RigaRicevimento,
                              giacenza, in_quarantena)
from magazzino.tests.test_magazzino import scena  # noqa: F401


def _ricevi(s, q=10):
    azienda, magazzino, cliente, fornitore, monitor, _ = s
    r = Ricevimento.objects.create(azienda=azienda, magazzino=magazzino, fornitore=fornitore)
    RigaRicevimento.objects.create(ricevimento=r, prodotto=monitor, quantita=q, costo=Decimal("100"))
    operazioni.ricevi(r)
    return r


def test_quarantena_e_superato(scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, _ = scena
    parametri.scrivi("magazzino.giacenza_negativa", False, azienda)
    PuntoControllo.objects.create(azienda=azienda, nome="Schermo integro", prodotto=monitor)
    r = _ricevi(scena)
    c = ControlloQualita.objects.get()
    assert c.ricevimento == r and in_quarantena(monitor) == 10 and giacenza(monitor) == 10
    consegna = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=consegna, prodotto=monitor, quantita=1)
    with pytest.raises(ValidationError, match="insufficiente"):
        operazioni.spedisci(consegna)                                     # in quarantena non si spedisce
    qualita_merce.registra(c, ControlloQualita.SUPERATO)
    assert in_quarantena(monitor) == 0 and giacenza(monitor) == 10
    operazioni.spedisci(consegna)


def test_respinto(scena):  # noqa: F811
    azienda, *_ = scena
    PuntoControllo.objects.create(azienda=azienda, nome="Imballo", fase="ricevimento")
    _ricevi(scena)
    c = ControlloQualita.objects.get()
    with pytest.raises(ValidationError):
        qualita_merce.registra(c, ControlloQualita.RESPINTO)               # serve il motivo
    qualita_merce.registra(c, ControlloQualita.RESPINTO, nota="scatole bagnate")
    nc = NonConformita.objects.get()
    assert nc.fornitore == scena[3] and nc.quantita == 10 and in_quarantena(scena[4]) == 10


def test_controllo_prima_della_spedizione(client, scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, _ = scena
    _ricevi(scena)
    PuntoControllo.objects.create(azienda=azienda, nome="Collaudo finale", fase="consegna", prodotto=monitor)
    consegna = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=consegna, prodotto=monitor, quantita=1)
    with pytest.raises(ValidationError, match="Collaudo finale"):
        operazioni.spedisci(consegna)
    operazioni.segna_pronta(consegna)                                     # i controlli nascono con la consegna pronta
    c = ControlloQualita.objects.get(consegna=consegna)
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    client.post(f"/magazzino/controlli/{c.pk}/bottone/supera/")
    operazioni.spedisci(consegna)
    assert consegna.stato == "fatto"
