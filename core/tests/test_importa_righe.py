"""Import di testata e righe: righe consecutive con la stessa testata formano un documento, le colonne «riga.» vanno
nelle righe, totali ricalcolati, errori con il numero di riga, aggiornamento che sostituisce le righe."""
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

import fiscale
import prodotti
from contatti.models import Contatto
from core import importa
from core.models import Azienda
from core.viste import registry
from vendite.models import OrdineVendita


@pytest.fixture
def s(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    Contatto.objects.create(azienda=azienda, nome="Rossi", cliente=True)
    Contatto.objects.create(azienda=azienda, nome="Verdi", cliente=True)
    richiesta = type("R", (), {"user": User.objects.create_superuser("root", "r@x.it", "x"), "azienda": azienda})()
    vista = next(v for v in registry.viste_di("vendite") if v.slug == "ordini")
    return {"azienda": azienda, "r": richiesta, "vista": vista}


def test_documenti_con_righe(s):
    campi = dict(importa.campi(s["vista"]))
    assert "riga.descrizione" in campi and campi["riga.quantita"].startswith("Riga ·")
    intestazioni = ["Cliente", "Data", "Descrizione", "Quantità", "Prezzo"]
    righe = [["Rossi", "01/11/2026", "Sito", "1", "1000"], ["Rossi", "01/11/2026", "Hosting", "12", "10"],
             ["Verdi", "02/11/2026", "Logo", "1", "300"]]
    mappa = ["cliente", "data", "riga.descrizione", "riga.quantita", "riga.prezzo"]
    nuovi, aggiornati, errori = importa.esegui(s["vista"], s["r"], intestazioni, righe, mappa, False)
    assert errori == [] and nuovi == 2
    rossi = OrdineVendita.objects.get(cliente__nome="Rossi")
    assert rossi.righe.count() == 2 and rossi.imponibile == Decimal("1120.00")


def test_errori_con_riga(s):
    righe = [["Rossi", "Sito", "uno"]]
    _, _, errori = importa.esegui(s["vista"], s["r"], ["Cliente", "Descrizione", "Quantità"], righe, ["cliente", "riga.descrizione", "riga.quantita"], False)
    assert errori == [{"riga": 2, "campo": "Riga · quantita", "messaggio": "Inserisci un numero."}] and not OrdineVendita.objects.exists()
