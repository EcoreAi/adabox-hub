from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

import fiscale
import prodotti
from core.models import Azienda
from prodotti import hooks
from prodotti.models import Listino, PrezzoListino, Prodotto
from prodotti.prezzi import prezzo


@pytest.fixture
def dati(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    return Azienda.objects.get(pk=1)


def test_predefiniti(dati):
    p = Prodotto.objects.create(azienda=dati, nome="Vite")
    assert p.unita.simbolo == "pz" and p.aliquota_iva.codice == "22" and p.a_magazzino


def test_codice_unico_per_azienda(dati):
    Prodotto.objects.create(azienda=dati, nome="A", codice="X1")
    with pytest.raises(ValidationError, match="codice"):
        Prodotto(azienda=dati, nome="B", codice="X1").full_clean()
    Prodotto(azienda=Azienda.objects.create(nome="Zeta"), nome="B", codice="X1").full_clean()


def test_prezzo_da_listino_a_scaglioni(dati):
    p = Prodotto.objects.create(azienda=dati, nome="Monitor", prezzo_vendita=Decimal("100"))
    l = Listino.objects.create(azienda=dati, nome="Rivenditori")
    PrezzoListino.objects.create(listino=l, prodotto=p, quantita_minima=1, prezzo=Decimal("90"))
    PrezzoListino.objects.create(listino=l, prodotto=p, quantita_minima=10, prezzo=Decimal("80"))
    assert prezzo(p) == Decimal("100") and prezzo(p, l, 1) == Decimal("90") and prezzo(p, l, 25) == Decimal("80")
    altro = Prodotto.objects.create(azienda=dati, nome="Senza listino", prezzo_vendita=Decimal("5"))
    assert prezzo(altro, l, 3) == Decimal("5")


def test_crea_dalla_vista_con_codice(client, superuser, dati):
    r = client.post("/prodotti/prodotti/nuovo/", {"nome": "Tastiera", "tipo": "bene", "unita": 1,
                                                  "prezzo_vendita": "25", "costo": "10", "aliquota_iva": 1,
                                                  "scorta_minima": "0", "attivo": "on"})
    assert r.status_code == 302 and Prodotto.objects.get(nome="Tastiera").codice == "P00001"


def test_listino_con_righe(client, superuser, dati):
    p = Prodotto.objects.create(azienda=dati, nome="Mouse", prezzo_vendita=Decimal("20"))
    dati_form = {"nome": "Scuole", "attivo": "on", "righe0-TOTAL_FORMS": "1", "righe0-INITIAL_FORMS": "0",
                 "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000",
                 "righe0-0-prodotto": p.pk, "righe0-0-quantita_minima": "1", "righe0-0-prezzo": "15"}
    assert client.post("/prodotti/listini/nuovo/", dati_form).status_code == 302
    listino = Listino.objects.get(nome="Scuole")
    assert prezzo(p, listino) == Decimal("15")
    assert "Mouse" in client.get(f"/prodotti/listini/{listino.pk}/").content.decode()


def test_demo(dati):
    hooks.demo(None)
    hooks.demo(None)                                                 # idempotente
    assert Prodotto.objects.count() == len(hooks.DEMO)
    assert Prodotto.objects.get(nome="Corso di formazione").aliquota_iva.codice == "N4"
    assert Listino.objects.get(nome="Rivenditori").prezzi.count() == 8


def test_dashboard(client, superuser, dati):
    hooks.demo(None)
    schede = {s["slug"]: s for s in client.get("/dashboard/").context["schede"]}
    assert schede["prodotti"]["kpi"][0]["valore"] == len(hooks.DEMO)
