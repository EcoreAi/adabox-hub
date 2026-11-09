"""Costi accessori: ripartizione per valore, quantità e peso sui carichi dei ricevimenti, costo di magazzino
ricalcolato anche per le uscite, annullo che torna ai costi di prima, pagina."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from magazzino import accessori, costi, operazioni
from magazzino.models import Consegna, CostoAccessorio, Movimento, Ricevimento, RigaConsegna, RigaRicevimento
from magazzino.tests.test_magazzino import scena  # noqa: F401
from prodotti.models import Prodotto


@pytest.fixture
def s(scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, corso = scena
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo", peso=Decimal("0.1"))
    monitor.peso = Decimal("5")
    monitor.save()
    r = Ricevimento.objects.create(azienda=azienda, magazzino=magazzino, fornitore=fornitore)
    RigaRicevimento.objects.create(ricevimento=r, prodotto=monitor, quantita=10, costo=Decimal("100"))      # 1000 €
    RigaRicevimento.objects.create(ricevimento=r, prodotto=cavo, quantita=100, costo=Decimal("10"))         # 1000 €
    operazioni.ricevi(r)
    return {"azienda": azienda, "magazzino": magazzino, "cliente": cliente, "monitor": monitor, "cavo": cavo, "r": r}


def _costo(s, criterio, importo="200"):
    c = CostoAccessorio.objects.create(azienda=s["azienda"], descrizione="Trasporto", importo=Decimal(importo), criterio=criterio)
    c.ricevimenti.add(s["r"])
    return c


def test_valore_e_uscite(s):
    c = Consegna.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], cliente=s["cliente"])
    RigaConsegna.objects.create(consegna=c, prodotto=s["monitor"], quantita=2)
    operazioni.spedisci(c)
    costo = _costo(s, "valore")
    accessori.applica(costo)
    assert costi.costo_corrente(s["monitor"]) == Decimal("110.0000") and costi.costo_corrente(s["cavo"]) == Decimal("11.0000")
    uscita = Movimento.objects.get(prodotto=s["monitor"], tipo="scarico")
    assert uscita.costo_unitario == Decimal("110.0000")                     # anche l'uscita già fatta
    with pytest.raises(ValidationError):
        accessori.applica(costo)
    accessori.annulla(costo)
    assert costi.costo_corrente(s["monitor"]) == Decimal("100.0000") and costo.ripartizioni.count() == 0


def test_quantita_e_peso(s):
    righe = {m.prodotto.nome: q for m, _, q in accessori.anteprima(_costo(s, "quantita", "110"))}
    assert righe == {"Monitor": Decimal("10.00"), "Cavo": Decimal("100.00")}
    righe = {m.prodotto.nome: q for m, _, q in accessori.anteprima(_costo(s, "peso", "60"))}
    assert righe == {"Monitor": Decimal("50.00"), "Cavo": Decimal("10.00")}            # 50 kg e 10 kg


def test_pagina(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    costo = _costo(s, "valore")
    assert "Anteprima della ripartizione" in client.get(f"/magazzino/accessori/{costo.pk}/").content.decode()
    client.post(f"/magazzino/accessori/{costo.pk}/bottone/applica/")
    costo.refresh_from_db()
    assert costo.stato == "applicato"
