"""Consegna pronta, evasione parziale con residuo (anche dalla lettura dei codici), storno di consegne e ricevimenti
già fatti, annullo del ricevimento in bozza."""
import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from core import parametri
from magazzino import operazioni
from magazzino.models import Consegna, Movimento, Ricevimento, RigaConsegna, RigaRicevimento, giacenza
from magazzino.tests.test_magazzino import scena  # noqa: F401  (fixture)
from prodotti.models import Prodotto


@pytest.fixture
def s(scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, corso = scena
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo", codice_barre="8000000000024")
    r = Ricevimento.objects.create(azienda=azienda, magazzino=magazzino, fornitore=fornitore)
    RigaRicevimento.objects.create(ricevimento=r, prodotto=monitor, quantita=10, costo=Decimal("100"))
    RigaRicevimento.objects.create(ricevimento=r, prodotto=cavo, quantita=20, costo=Decimal("2"))
    operazioni.ricevi(r)
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente, riferimento="OV/7",
                                origine_tipo=ContentType.objects.get_for_model(Prodotto), origine_id=monitor.pk)
    RigaConsegna.objects.create(consegna=c, prodotto=monitor, quantita=4)
    RigaConsegna.objects.create(consegna=c, prodotto=cavo, quantita=6)
    return {"azienda": azienda, "magazzino": magazzino, "monitor": monitor, "cavo": cavo, "ricevimento": r, "consegna": c,
            "fornitore": fornitore}


def test_pronta_e_spedita(s):
    c = s["consegna"]
    operazioni.segna_pronta(c)
    assert c.stato == "pronto"
    with pytest.raises(ValidationError):
        operazioni.segna_pronta(c)
    operazioni.spedisci(c)
    assert c.stato == "fatto" and giacenza(s["monitor"]) == 6


def test_dividi_con_residuo(s):
    c = s["consegna"]
    righe = {r.prodotto.nome: r for r in c.righe.select_related("prodotto")}
    residuo = operazioni.dividi(c, {righe["Monitor"].pk: 3, righe["Cavo"].pk: 0})
    assert list(c.righe.values_list("prodotto__nome", "quantita")) == [("Monitor", Decimal("3"))]
    assert sorted(residuo.righe.values_list("prodotto__nome", "quantita")) == [("Cavo", Decimal("6")), ("Monitor", Decimal("1"))]
    assert residuo.origine_id == c.origine_id and residuo.riferimento == "OV/7" and residuo.stato == "bozza" and "Residuo di" in residuo.note
    assert operazioni.dividi(c, {}) is None
    with pytest.raises(ValidationError):
        operazioni.dividi(c, {c.righe.get().pk: 9})


def test_storno_della_consegna(s):
    c = s["consegna"]
    operazioni.spedisci(c)
    assert giacenza(s["monitor"]) == 6
    operazioni.storna(c)
    c.refresh_from_db()
    assert c.stato == "annullato" and giacenza(s["monitor"]) == 10 and giacenza(s["cavo"]) == 20
    rientro = Movimento.objects.filter(prodotto=s["monitor"], causale__startswith="Storno").get()
    assert rientro.quantita == 4 and rientro.tipo == "carico" and rientro.costo_unitario is not None
    with pytest.raises(ValidationError):
        operazioni.storna(c)


def test_consegna_in_fattura_non_si_storna(s):
    from contatti.models import Contatto
    from fatturazione.models import Fattura, RiferimentoDDT
    c = s["consegna"]
    operazioni.spedisci(c)
    f = Fattura.objects.create(azienda=s["azienda"], cliente=c.cliente)
    RiferimentoDDT.objects.create(fattura=f, numero=c.numero, data=c.data)
    with pytest.raises(ValidationError, match="nota di credito"):
        operazioni.storna(c)


def test_storno_e_annullo_del_ricevimento(s, client):
    parametri.scrivi("magazzino.giacenza_negativa", False, s["azienda"])
    operazioni.spedisci(s["consegna"])
    with pytest.raises(ValidationError, match="non c'è più"):
        operazioni.storna(s["ricevimento"])                              # 4 monitor già spediti
    operazioni.storna(s["consegna"])
    operazioni.storna(s["ricevimento"])
    assert giacenza(s["monitor"]) == 0
    r = Ricevimento.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], fornitore=s["fornitore"])
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get(f"/magazzino/ricevimenti/{r.pk}/").content.decode()
    assert "bottone/annulla/" in html and "bottone/storna/" not in html
    client.post(f"/magazzino/ricevimenti/{r.pk}/bottone/annulla/")
    r.refresh_from_db()
    assert r.stato == "annullato"


def test_residuo_dalla_lettura(s, client):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    c = s["consegna"]
    url = f"/magazzino/lettura/consegna/{c.pk}/"
    client.post(url, {"letture": json.dumps({s["monitor"].pk: 4, s["cavo"].pk: 2}), "residuo": "1", "chiudi": "1"})
    c.refresh_from_db()
    assert c.stato == "fatto" and giacenza(s["cavo"]) == 18
    residuo = Consegna.objects.exclude(pk=c.pk).get()
    assert list(residuo.righe.values_list("prodotto__nome", "quantita")) == [("Cavo", Decimal("4"))]
    client.post(f"/magazzino/lettura/consegna/{residuo.pk}/", {"letture": json.dumps({s["cavo"].pk: 4})})
    residuo.refresh_from_db()
    assert residuo.stato == "pronto"
    html = client.get(f"/magazzino/consegne/{residuo.pk}/").content.decode()
    assert "bottone/spedisci/" in html and "bottone/pronta/" not in html
