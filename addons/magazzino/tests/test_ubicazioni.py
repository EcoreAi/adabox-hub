"""Ubicazioni: albero nello stesso magazzino, carichi nella predefinita, uscite da dove ce n'è di più, trasferimenti
che non cambiano il costo, pagine."""
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

import fiscale
import prodotti
from contatti.models import Contatto
from core import parametri
from core.models import Azienda
from magazzino import costi, operazioni
from magazzino.models import (Consegna, Magazzino, Movimento, Ricevimento, RigaConsegna, RigaRicevimento, Ubicazione,
                              giacenza)
from prodotti.models import Prodotto

D = Decimal


@pytest.fixture
def s(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    m = Magazzino.predefinito_per(azienda)
    a = Ubicazione.objects.create(magazzino=m, codice="A", predefinita=True)
    a1 = Ubicazione.objects.create(magazzino=m, codice="A-01", padre=a, nome="Scaffale 1")
    b = Ubicazione.objects.create(magazzino=m, codice="B")
    return {"azienda": azienda, "m": m, "a": a, "a1": a1, "b": b,
            "p": Prodotto.objects.create(azienda=azienda, nome="Monitor", costo=D("90")),
            "cliente": Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True),
            "fornitore": Contatto.objects.create(azienda=azienda, nome="Grossista Spa", fornitore=True)}


def test_albero_e_predefinita(s):
    assert s["a1"].percorso == "A / A-01" and s["a1"].azienda == s["azienda"]
    s["a"].padre = s["a1"]
    with pytest.raises(ValidationError, match="dentro sé stessa"):
        s["a"].full_clean()
    altro = Magazzino.objects.create(azienda=s["azienda"], nome="Negozio")
    with pytest.raises(ValidationError, match="stesso magazzino"):
        Ubicazione(magazzino=altro, codice="X", padre=s["a"]).full_clean()
    Ubicazione.objects.create(magazzino=s["m"], codice="C", predefinita=True)
    assert Ubicazione.predefinita_di(s["m"]).codice == "C"


def test_carichi_uscite_e_trasferimenti(s):
    r = Ricevimento.objects.create(azienda=s["azienda"], magazzino=s["m"], fornitore=s["fornitore"])
    RigaRicevimento.objects.create(ricevimento=r, prodotto=s["p"], quantita=10, costo=D("100"))
    RigaRicevimento.objects.create(ricevimento=r, prodotto=s["p"], quantita=4, costo=D("100"), ubicazione=s["b"])
    operazioni.ricevi(r)
    assert giacenza(s["p"], s["m"], s["a"]) == 10 and giacenza(s["p"], s["m"], s["b"]) == 4
    c = Consegna.objects.create(azienda=s["azienda"], magazzino=s["m"], cliente=s["cliente"])
    RigaConsegna.objects.create(consegna=c, prodotto=s["p"], quantita=3)
    operazioni.spedisci(c)
    assert giacenza(s["p"], s["m"], s["a"]) == 7                                   # da dove ce n'era di più
    operazioni.trasferisci(s["p"], 5, s["m"], s["m"], s["a"], s["a1"])
    assert giacenza(s["p"], s["m"], s["a1"]) == 5 and giacenza(s["p"], s["m"]) == 11
    negozio = Magazzino.objects.create(azienda=s["azienda"], nome="Negozio")
    operazioni.trasferisci(s["p"], 2, s["m"], negozio, s["b"])
    assert giacenza(s["p"], negozio) == 2 and giacenza(s["p"]) == 11
    stato, _ = costi.ripercorri(s["p"])
    assert stato.quantita == 11 and costi.q2(stato.valore) == D("1100.00")       # spostare non cambia il valore
    with pytest.raises(ValidationError, match="coincidono"):
        operazioni.trasferisci(s["p"], 1, s["m"], s["m"], s["a"], s["a"])
    parametri.scrivi("magazzino.giacenza_negativa", False, s["azienda"])
    with pytest.raises(ValidationError, match="insufficiente"):
        operazioni.trasferisci(s["p"], 50, s["m"], negozio, s["a1"])


def test_ubicazione_di_un_altro_magazzino(s):
    negozio = Magazzino.objects.create(azienda=s["azienda"], nome="Negozio")
    m = Movimento(azienda=s["azienda"], prodotto=s["p"], magazzino=negozio, ubicazione=s["a"], quantita=1)
    with pytest.raises(ValidationError, match="altro magazzino"):
        m.full_clean()


def test_pagine(client, superuser, s):
    Movimento.objects.create(azienda=s["azienda"], prodotto=s["p"], magazzino=s["m"], quantita=6)
    pagina = client.get(reverse("magazzino:per_ubicazione")).content.decode()
    assert "Monitor" in pagina and "A" in pagina
    dettaglio = client.get(reverse("magazzino:ubicazioni_dettaglio", args=[s["a"].pk])).content.decode()
    assert "Merce in A" in dettaglio and "Sposta da qui" in dettaglio
    assert client.get(reverse("magazzino:trasferisci") + f"?da=u{s['a'].pk}").status_code == 200
    client.post(reverse("magazzino:trasferisci"), {"prodotto": s["p"].pk, "quantita": "2,5", "da": f"u{s['a'].pk}",
                                                   "a": f"u{s['b'].pk}"})
    assert giacenza(s["p"], s["m"], s["b"]) == D("2.5")
    altra = Azienda.objects.create(nome="Altra")
    estranea = Ubicazione.objects.create(magazzino=Magazzino.predefinito_per(altra), codice="Z")
    client.post(reverse("magazzino:trasferisci"), {"prodotto": s["p"].pk, "quantita": "1", "da": f"u{s['a'].pk}",
                                                   "a": f"u{estranea.pk}"})
    assert not Movimento.objects.filter(ubicazione=estranea).exists()
    assert client.get(reverse("magazzino:ubicazioni_lista")).status_code == 200
