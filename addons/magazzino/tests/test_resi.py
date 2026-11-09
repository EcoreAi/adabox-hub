"""Resi: dal DDT al reso, autorizzazione, esito per riga, rientro a magazzino o scarto, nota di credito con le sole
righe rese al prezzo della fattura, pagine e permessi dei bottoni."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from fatturazione import operazioni as fatture
from fatturazione.models import Fattura
from magazzino import operazioni, resi
from magazzino.models import Consegna, Reso, Ricevimento, RigaConsegna, RigaRicevimento, giacenza
from magazzino.tests.test_magazzino import scena  # noqa: F401  (fixture)
from prodotti.models import Prodotto


@pytest.fixture
def s(scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, corso = scena
    cliente.partita_iva = "12345678903"
    cliente.save()
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo", prezzo_vendita=Decimal("10"))
    r = Ricevimento.objects.create(azienda=azienda, magazzino=magazzino, fornitore=fornitore)
    RigaRicevimento.objects.create(ricevimento=r, prodotto=monitor, quantita=10, costo=Decimal("100"))
    RigaRicevimento.objects.create(ricevimento=r, prodotto=cavo, quantita=10, costo=Decimal("2"))
    operazioni.ricevi(r)
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=c, prodotto=monitor, quantita=3)
    RigaConsegna.objects.create(consegna=c, prodotto=cavo, quantita=5)
    operazioni.spedisci(c)
    return {"azienda": azienda, "c": c, "monitor": monitor, "cavo": cavo}


def _fattura(s):
    f = fatture.da_consegne([s["c"]])
    for r in f.righe.all():
        r.prezzo = Decimal("200") if r.prodotto == s["monitor"] else Decimal("10")
        r.save()
    f.ricalcola()
    Fattura.objects.filter(pk=f.pk).update(stato=Fattura.EMESSA, numero="7/2026")
    return Fattura.objects.get(pk=f.pk)


def test_dal_ddt_al_rientro(s):
    reso = resi.da_consegna(s["c"])
    assert reso.numero.startswith("RES/") and reso.righe.count() == 2 and reso.stato == "richiesto"
    monitor = reso.righe.get(prodotto=s["monitor"])
    monitor.quantita, monitor.esito = 1, "magazzino"
    monitor.save()
    cavo = reso.righe.get(prodotto=s["cavo"])
    with pytest.raises(ValidationError):
        resi.rientra(reso)                                                    # prima l'autorizzazione
    resi.autorizza(reso)
    with pytest.raises(ValidationError, match="esito"):
        resi.rientra(reso)                                                    # il cavo è ancora da ispezionare
    cavo.quantita, cavo.esito = 2, "scarto"
    cavo.save()
    resi.rientra(reso)
    assert reso.stato == "rientrato" and giacenza(s["monitor"]) == 8 and giacenza(s["cavo"]) == 5   # lo scarto non rientra


def test_nota_di_credito_con_le_righe_rese(s):
    fattura = _fattura(s)
    reso = resi.da_consegna(s["c"])
    assert reso.fattura_id == fattura.pk                                      # trovata dal DDT citato
    reso.righe.filter(prodotto=s["cavo"]).delete()
    reso.righe.update(quantita=1, esito="magazzino")
    resi.autorizza(reso)
    resi.rientra(reso)
    nota = resi.nota_di_credito(reso)
    assert nota.tipo == Fattura.NOTA_CREDITO and nota.fattura_origine == fattura and nota.stato == "bozza"
    riga, = nota.righe.all()
    assert (riga.prodotto, riga.quantita, riga.prezzo) == (s["monitor"], Decimal("1"), Decimal("200"))
    reso.refresh_from_db()
    assert reso.stato == "chiuso" and reso.nota_credito == nota
    with pytest.raises(ValidationError, match="già"):
        resi.nota_di_credito(reso)


def test_senza_fattura_e_prodotto_non_fatturato(s):
    reso = resi.da_consegna(s["c"])
    resi.autorizza(reso)
    with pytest.raises(ValidationError, match="Non trovo la fattura"):
        resi.nota_di_credito(reso)
    resi.rifiuta(reso)
    assert reso.stato == "rifiutato"


def test_pagine(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get(f"/magazzino/consegne/{s['c'].pk}/").content.decode()
    assert "bottone/reso/" in html
    r = client.post(f"/magazzino/consegne/{s['c'].pk}/bottone/reso/")
    reso = Reso.objects.get()
    assert r.status_code == 302 and r.url.endswith(f"/magazzino/resi/{reso.pk}/")
    html = client.get(f"/magazzino/resi/{reso.pk}/").content.decode()
    assert "Merce resa" in html and "bottone/autorizza/" in html and "bottone/rientra/" not in html
    client.post(f"/magazzino/resi/{reso.pk}/bottone/autorizza/")
    assert "bottone/rientra/" in client.get(f"/magazzino/resi/{reso.pk}/").content.decode()
