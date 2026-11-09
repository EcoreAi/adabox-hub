"""Garanzie e riparazioni: garanzia dal seriale consegnato, riparazione in garanzia senza preventivo né fattura,
riparazione a pagamento con preventivo, ricambi scaricati e fattura, verifica garanzia."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from magazzino import operazioni
from magazzino.models import Consegna, Ricevimento, RigaConsegna, RigaRicevimento, Tracciamento, giacenza
from magazzino.tests.test_magazzino import scena  # noqa: F401
from prodotti.models import Prodotto
from riparazioni import servizi
from riparazioni.models import GaranziaProdotto, Riparazione, RigaRicambio


@pytest.fixture
def s(scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, _ = scena
    Tracciamento.objects.create(prodotto=monitor, tipo=Tracciamento.SERIALE)
    GaranziaProdotto.objects.create(azienda=azienda, prodotto=monitor, mesi=24, mesi_fornitore=12)
    scheda = Prodotto.objects.create(azienda=azienda, nome="Scheda video", prezzo_vendita=Decimal("80"))
    r = Ricevimento.objects.create(azienda=azienda, magazzino=magazzino, fornitore=fornitore)
    RigaRicevimento.objects.create(ricevimento=r, prodotto=monitor, quantita=1, lotti="SN001")
    RigaRicevimento.objects.create(ricevimento=r, prodotto=scheda, quantita=5)
    operazioni.ricevi(r)
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=c, prodotto=monitor, quantita=1, lotti="SN001")
    operazioni.spedisci(c)
    return {"azienda": azienda, "magazzino": magazzino, "cliente": cliente, "monitor": monitor, "scheda": scheda, "consegna": c}


def test_garanzia_dal_seriale(s):
    g = servizi.garanzia(s["azienda"], seriale="SN001")
    assert g["attiva"] and g["consegna"] == s["consegna"] and g["fino_al"].year == s["consegna"].data.year + 2
    assert servizi.garanzia(s["azienda"], seriale="NONC'E") is None


def test_in_garanzia(s):
    r = Riparazione.objects.create(azienda=s["azienda"], cliente=s["cliente"], prodotto=s["monitor"], seriale="SN001", difetto="Non si accende",
                                   magazzino=s["magazzino"], ore=Decimal(1))
    servizi.accetta(r)
    assert r.numero.startswith("RIP/") and r.in_garanzia and r.recupero_fornitore and r.totale == 0
    servizi.preventivo(r)
    assert r.stato == "approvata"
    with pytest.raises(ValidationError):
        servizi.fattura(r)


def test_a_pagamento(client, s):
    r = Riparazione.objects.create(azienda=s["azienda"], cliente=s["cliente"], descrizione_bene="PC del cliente", difetto="Schermo nero",
                                   magazzino=s["magazzino"], ore=Decimal("1.5"), tariffa=Decimal(40))
    servizi.accetta(r)
    RigaRicambio.objects.create(riparazione=r, prodotto=s["scheda"], quantita=1)
    assert not r.in_garanzia and r.totale == Decimal("140.00")
    servizi.preventivo(r)
    servizi.approva(r)
    servizi.avvia(r)
    servizi.pronta(r)
    assert giacenza(s["scheda"]) == 4
    f = servizi.fattura(r)
    assert f.imponibile == Decimal("140.00")
    servizi.riconsegna(r)
    assert r.stato == "riconsegnata"
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    assert "In garanzia" in client.get("/riparazioni/verifica/?seriale=SN001").content.decode()
    assert "Manodopera" in client.get(f"/riparazioni/riparazioni/{r.pk}/").content.decode()
