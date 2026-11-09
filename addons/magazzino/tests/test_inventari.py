"""Inventari: fotografia del teorico (anche per lotto), contato scritto, letto e importato, approvazione con rettifiche
al costo, movimenti durante la conta, lotti obbligatori, conta ciclica, pagine e pacchetto per lo studio."""
import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from core import parametri
from magazzino import inventari, operazioni
from magazzino.models import Inventario, Lotto, Movimento, Ricevimento, RigaRicevimento, Tracciamento, giacenza
from magazzino.tests.test_magazzino import scena  # noqa: F401  (fixture)
from prodotti.models import Confezione, Prodotto


@pytest.fixture
def s(scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, corso = scena
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo", codice_barre="8000000000024", costo=Decimal("2"))
    Confezione.objects.create(prodotto=cavo, nome="Scatola", quantita=10, codice_barre="8000000000031")
    r = Ricevimento.objects.create(azienda=azienda, magazzino=magazzino, fornitore=fornitore)
    RigaRicevimento.objects.create(ricevimento=r, prodotto=monitor, quantita=10, costo=Decimal("100"))
    RigaRicevimento.objects.create(ricevimento=r, prodotto=cavo, quantita=50, costo=Decimal("2"))
    operazioni.ricevi(r)
    return {"azienda": azienda, "magazzino": magazzino, "monitor": monitor, "cavo": cavo, "corso": corso, "fornitore": fornitore}


def test_fotografia_conta_e_approvazione(s):
    inv = inventari.crea(s["azienda"], s["magazzino"])
    teorici = {r.prodotto.nome: r.teorico for r in inv.righe.select_related("prodotto")}
    assert teorici == {"Monitor": 10, "Cavo": 50} and inv.numero.startswith("INV/")          # il servizio no
    righe = {r.prodotto.nome: r for r in inv.righe.select_related("prodotto")}
    inventari.scrivi(inv, {righe["Monitor"].pk: "8", righe["Cavo"].pk: ""})
    with pytest.raises(ValidationError):
        inventari.scrivi(inv, {righe["Monitor"].pk: "-1"})
    inventari.approva(inv)
    assert giacenza(s["monitor"]) == 8 and giacenza(s["cavo"]) == 50                          # il cavo non contato resta
    m = Movimento.objects.get(tipo="rettifica")
    assert m.quantita == -2 and "INV/" in m.causale
    righe["Monitor"].refresh_from_db()
    assert righe["Monitor"].rettifica == -2 and righe["Monitor"].valore_rettifica == Decimal("-200.00")
    with pytest.raises(ValidationError):
        inventari.approva(inv)


def test_movimenti_durante_la_conta_e_non_contati_a_zero(s):
    inv = inventari.crea(s["azienda"], s["magazzino"])
    Movimento.objects.create(azienda=s["azienda"], prodotto=s["monitor"], magazzino=s["magazzino"], quantita=-3)   # venduti durante la conta
    righe = {r.prodotto.nome: r for r in inv.righe.select_related("prodotto")}
    inventari.scrivi(inv, {righe["Monitor"].pk: "7"})
    inventari.approva(inv, non_contati_zero=True)
    assert giacenza(s["monitor"]) == 7 and giacenza(s["cavo"]) == 0


def test_letti_e_importati(s):
    inv = inventari.crea(s["azienda"], s["magazzino"])
    inventari.aggiungi_letti(inv, {s["cavo"].pk: Decimal(10)})
    inventari.aggiungi_letti(inv, {s["cavo"].pk: Decimal(10)})
    assert inv.righe.get(prodotto=s["cavo"]).contato == 20
    nuovo = Prodotto.objects.create(azienda=s["azienda"], nome="Mouse", codice="MS1")
    letti, scartati = inventari.importa(inv, "codice;quantità\n8000000000031;3\nMS1;4\nboh;1\n".encode())
    assert letti == 2 and scartati == ["boh"]
    assert inv.righe.get(prodotto=s["cavo"]).contato == 30 and inv.righe.get(prodotto=nuovo).contato == 4


def test_lotti(s):
    Tracciamento.objects.create(prodotto=s["cavo"], tipo=Tracciamento.LOTTO)
    lotto = Lotto.objects.create(azienda=s["azienda"], prodotto=s["cavo"], codice="L1")
    Movimento.objects.filter(prodotto=s["cavo"]).update(lotto=lotto)
    inv = inventari.crea(s["azienda"], s["magazzino"])
    riga = inv.righe.get(prodotto=s["cavo"])
    assert riga.lotto == lotto and riga.teorico == 50
    with pytest.raises(ValidationError, match="più lotti"):
        Lotto.objects.create(azienda=s["azienda"], prodotto=s["cavo"], codice="L2")
        inv.righe.create(prodotto=s["cavo"], lotto=Lotto.objects.get(codice="L2"), teorico=0)
        inventari.aggiungi_letti(inv, {s["cavo"].pk: Decimal(1)})
    inventari.scrivi(inv, {riga.pk: "45"})
    inventari.approva(inv)
    assert giacenza(s["cavo"], lotto=lotto) == 45


def test_conta_ciclica(s):
    assert inventari.conta_ciclica() == 0                                      # spenta
    parametri.scrivi("magazzino.conta_ciclica", 1, s["azienda"])
    assert inventari.conta_ciclica() == 1
    primo = Inventario.objects.get(ciclica=True)
    assert primo.righe.count() == 1 and inventari.conta_ciclica() == 0         # la precedente è ancora in conta
    riga = primo.righe.get()
    inventari.scrivi(primo, {riga.pk: str(riga.teorico)})
    inventari.approva(primo)
    inventari.conta_ciclica()
    secondo = Inventario.objects.filter(ciclica=True, stato="conta").get()
    assert secondo.righe.get().prodotto != riga.prodotto                       # tocca a quello mai contato


def test_pagine_e_pacchetto(client, s):
    root = User.objects.create_superuser("root", "r@x.it", "x")
    client.force_login(root)
    r = client.post("/magazzino/inventari/nuovo/", {"magazzino": s["magazzino"].pk, "data": "2026-11-09", "note": ""})
    assert r.status_code == 302
    inv = Inventario.objects.get()
    assert inv.righe.count() == 2
    html = client.get(f"/magazzino/inventari/{inv.pk}/conta/").content.decode()
    assert "Conta con il lettore" in html and "Teorico" not in html                         # conta alla cieca
    assert "Teorico" in client.get(f"/magazzino/inventari/{inv.pk}/conta/?teorico=1").content.decode()
    riga = inv.righe.get(prodotto=s["monitor"])
    client.post(f"/magazzino/inventari/{inv.pk}/conta/", {"azione": "salva", f"c_{riga.pk}": "9"})
    assert inv.righe.get(pk=riga.pk).contato == 9
    client.post(f"/magazzino/inventari/{inv.pk}/conta/", {"azione": "importa", "file": SimpleUploadedFile("c.csv", b"8000000000024;48")})
    assert inv.righe.get(prodotto=s["cavo"]).contato == 48
    client.post(f"/magazzino/lettura/inventario/{inv.pk}/", {"letture": json.dumps({s["cavo"].pk: 2})})
    assert inv.righe.get(prodotto=s["cavo"]).contato == 50
    assert "Conta INV/" in client.get("/magazzino/lettura/").content.decode()
    client.post(f"/magazzino/inventari/{inv.pk}/conta/", {"azione": "approva", f"c_{riga.pk}": "9"})
    inv.refresh_from_db()
    assert inv.stato == "approvato" and giacenza(s["monitor"]) == 9
    assert "Differenze" in client.get(f"/magazzino/inventari/{inv.pk}/conta/").content.decode()
    from magazzino.per_commercialista import differenze_inventario
    richiesta = type("R", (), {"user": root, "azienda": s["azienda"]})()
    file = dict(differenze_inventario(richiesta, 2026, 11, []))
    assert "-100,00" in file["magazzino/differenze-inventario.csv"].decode("utf-8-sig")
