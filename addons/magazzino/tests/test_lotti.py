"""Lotti e seriali: obbligo sulle righe dei prodotti tracciati, uscite per scadenza (FEFO), seriali unici,
tracciabilità verso fornitori e clienti, trasferimenti, pagine."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from magazzino import lotti, operazioni
from magazzino.models import (Consegna, Lotto, Magazzino, Movimento, Ricevimento, RigaConsegna, RigaRicevimento,
                              Tracciamento, giacenza)
from prodotti.models import Prodotto

D = Decimal
OGGI = datetime.date.today()


@pytest.fixture
def s(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    latte = Prodotto.objects.create(azienda=azienda, nome="Latte", costo=D("1"))
    router = Prodotto.objects.create(azienda=azienda, nome="Router", costo=D("50"))
    Tracciamento.objects.create(prodotto=latte, tipo=Tracciamento.LOTTO, scadenza=True)
    Tracciamento.objects.create(prodotto=router, tipo=Tracciamento.SERIALE)
    return {"azienda": azienda, "m": Magazzino.predefinito_per(azienda), "latte": latte, "router": router,
            "cliente": Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True),
            "fornitore": Contatto.objects.create(azienda=azienda, nome="Caseificio Spa", fornitore=True)}


def _ricevi(s, prodotto, quantita, testo):
    r = Ricevimento.objects.create(azienda=s["azienda"], magazzino=s["m"], fornitore=s["fornitore"])
    RigaRicevimento.objects.create(ricevimento=r, prodotto=prodotto, quantita=quantita, lotti=testo)
    operazioni.ricevi(r)
    return r


def _spedisci(s, prodotto, quantita, testo=""):
    c = Consegna.objects.create(azienda=s["azienda"], magazzino=s["m"], cliente=s["cliente"])
    RigaConsegna.objects.create(consegna=c, prodotto=prodotto, quantita=quantita, lotti=testo)
    operazioni.spedisci(c)
    return c


def test_lettura_della_riga(s):
    assert lotti.leggi("L1:5, L2:3", 8, s["latte"]) == [("L1", D(5)), ("L2", D(3))]
    assert lotti.leggi("L1", 8, s["latte"]) == [("L1", D(8))]
    assert lotti.leggi("SN1\nSN2", 2, s["router"]) == [("SN1", D(1)), ("SN2", D(1))]
    for testo, q, p, errore in [("L1:5", 8, "latte", "sommano"), ("L1, L2", 8, "latte", "quantità di ciascuno"),
                                ("SN1", 2, "router", "sommano"), ("SN1:2", 2, "router", "non valida"), ("A, A", 2, "router", "due volte")]:
        with pytest.raises(ValidationError, match=errore):
            lotti.leggi(testo, q, s[p])


def test_ricevimento_e_uscita_per_scadenza(s):
    with pytest.raises(ValidationError, match="scrivili sulla riga"):
        _ricevi(s, s["latte"], 10, "")
    _ricevi(s, s["latte"], 10, "L-TARDI:6, L-PRESTO:4")
    Lotto.objects.filter(codice="L-TARDI").update(scadenza=OGGI + datetime.timedelta(days=30))
    Lotto.objects.filter(codice="L-PRESTO").update(scadenza=OGGI + datetime.timedelta(days=5))
    _spedisci(s, s["latte"], 5)
    presto, tardi = Lotto.objects.get(codice="L-PRESTO"), Lotto.objects.get(codice="L-TARDI")
    assert lotti.saldo(presto) == 0 and lotti.saldo(tardi) == 5                    # prima quello che scade prima
    Lotto.objects.filter(pk=tardi.pk).update(scadenza=OGGI - datetime.timedelta(days=1))
    with pytest.raises(ValidationError, match="non scaduti"):
        _spedisci(s, s["latte"], 1)
    _spedisci(s, s["latte"], 1, "L-TARDI")                                          # scaduto, ma scelto apposta
    assert lotti.saldo(tardi) == 4


def test_seriali(s):
    _ricevi(s, s["router"], 2, "SN-001\nSN-002")
    assert Lotto.objects.get(codice="SN-001").seriale
    with pytest.raises(ValidationError, match="già in magazzino"):
        _ricevi(s, s["router"], 1, "SN-001")
    with pytest.raises(ValidationError, match="scrivi sulla riga quali"):
        _spedisci(s, s["router"], 1)
    _spedisci(s, s["router"], 1, "SN-002")
    with pytest.raises(ValidationError, match="non è in questo magazzino"):
        _spedisci(s, s["router"], 1, "SN-002")
    _ricevi(s, s["router"], 1, "SN-002")                                            # reso: torna in magazzino
    assert lotti.saldo(Lotto.objects.get(codice="SN-002")) == 1
    m = Movimento(azienda=s["azienda"], prodotto=s["router"], magazzino=s["m"], quantita=1)
    with pytest.raises(ValidationError, match="indicalo"):
        m.full_clean()


def test_trasferimento_di_un_lotto(s):
    _ricevi(s, s["latte"], 10, "L1")
    negozio = Magazzino.objects.create(azienda=s["azienda"], nome="Negozio")
    with pytest.raises(ValidationError, match="indica quale"):
        operazioni.trasferisci(s["latte"], 2, s["m"], negozio)
    l1 = Lotto.objects.get(codice="L1")
    operazioni.trasferisci(s["latte"], 2, s["m"], negozio, lotto=l1)
    assert lotti.saldo(l1, negozio) == 2 and giacenza(s["latte"]) == 10


def test_tracciabilita_e_pagine(client, superuser, s):
    _ricevi(s, s["latte"], 10, "L7")
    _spedisci(s, s["latte"], 3)
    l7 = Lotto.objects.get(codice="L7")
    pagina = client.get(reverse("magazzino:lotti_dettaglio", args=[l7.pk])).content.decode()
    assert "Caseificio Spa" in pagina and "Rossi Srl" in pagina and "Tracciabilità" in pagina
    assert "L7" in client.get(reverse("magazzino:lotti_lista")).content.decode()
    nuovo = Prodotto.objects.create(azienda=s["azienda"], nome="Formaggio")
    Movimento.objects.create(azienda=s["azienda"], prodotto=nuovo, magazzino=s["m"], quantita=4)
    client.post(reverse("magazzino:tracciamento_prodotto", args=[nuovo.pk]), {"tipo": "lotto"})
    assert not Tracciamento.objects.filter(prodotto=nuovo).exists()                 # c'è merce senza lotto
    Movimento.objects.create(azienda=s["azienda"], prodotto=nuovo, magazzino=s["m"], quantita=-4)
    client.post(reverse("magazzino:tracciamento_prodotto", args=[nuovo.pk]), {"tipo": "lotto", "scadenza": "1"})
    assert Tracciamento.objects.get(prodotto=nuovo).tipo == "lotto"
    assert "Tracciamento" in client.get(reverse("prodotti:prodotti_dettaglio", args=[nuovo.pk])).content.decode()
