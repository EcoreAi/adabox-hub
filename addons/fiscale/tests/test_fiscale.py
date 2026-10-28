import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

import fiscale
from fiscale import calcoli
from fiscale.models import AliquotaIva, TerminePagamento


@pytest.fixture
def dati(db):
    call_command("loaddata", str(Path(fiscale.__file__).parent / "data" / "iniziali.json"), verbosity=0)


def test_dati_iniziali_validi(dati):
    for a in AliquotaIva.objects.all():
        a.full_clean()
    for t in TerminePagamento.objects.all():
        t.full_clean()


def test_natura_obbligatoria_per_lo_zero(db):
    with pytest.raises(ValidationError, match="natura"):
        AliquotaIva(codice="Z", descrizione="Zero", percentuale=0).full_clean()
    with pytest.raises(ValidationError, match="solo per le aliquote allo 0"):
        AliquotaIva(codice="X", descrizione="X", percentuale=22, natura="N4").full_clean()


def test_rate_che_non_fanno_cento(db):
    with pytest.raises(ValidationError, match="sommano a 90"):
        TerminePagamento(nome="Rotto", rate=[{"giorni": 30, "percentuale": 90}]).full_clean()


def test_importo_riga():
    assert calcoli.importo_riga(3, Decimal("10.333"), 0) == Decimal("31.00")
    assert calcoli.importo_riga(1, Decimal("100"), Decimal("12.5")) == Decimal("87.50")
    assert calcoli.importo_riga(Decimal("2.5"), Decimal("0.1"), 0) == Decimal("0.25")


def test_riepilogo_e_totali(dati):
    iva22, iva10 = AliquotaIva.objects.get(codice="22"), AliquotaIva.objects.get(codice="10")
    esente = AliquotaIva.objects.get(codice="N4")
    righe = [(Decimal("10.05"), iva22), (Decimal("10.05"), iva22), (Decimal("100"), iva10), (Decimal("50"), esente)]
    riepilogo = calcoli.riepilogo_iva(righe)
    assert [(g["aliquota"].codice, g["imponibile"], g["imposta"]) for g in riepilogo] == [
        ("22", Decimal("20.10"), Decimal("4.42")), ("10", Decimal("100.00"), Decimal("10.00")),
        ("N4", Decimal("50.00"), Decimal("0.00"))]
    assert calcoli.totali(righe) == (Decimal("170.10"), Decimal("14.42"), Decimal("184.52"))


def test_scadenze(dati):
    rate = TerminePagamento.objects.get(nome="30-60 giorni fine mese")
    assert calcoli.scadenze(rate, datetime.date(2026, 1, 15), Decimal("100.01")) == [
        (datetime.date(2026, 2, 28), Decimal("50.01")), (datetime.date(2026, 3, 31), Decimal("50.00"))]
    assert calcoli.scadenze(None, datetime.date(2026, 1, 15), 10) == [(datetime.date(2026, 1, 15), Decimal("10.00"))]


def test_viste(client, superuser, dati):
    assert "IVA 22%" in client.get("/fiscale/aliquote/").content.decode()
    assert "30-60 giorni" in client.get("/fiscale/termini/").content.decode()
