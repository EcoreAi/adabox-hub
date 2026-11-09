"""Regole dei movimenti: classificazione all'importazione, condizioni (testi alternativi, controparte, segno, importo),
classificazione a mano che crea la regola, ripristino, movimenti classificati non abbinabili, export per lo studio."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from banca import abbina, classifica
from banca.models import Conto, MovimentoBanca, RegolaMovimento
from core.models import Azienda

IBAN = "IT60X0542811101000000123456"
CSV = """Data;Importo;Descrizione
02/11/2026;-2,50;COMMISSIONI BONIFICO
03/11/2026;-1500,00;F24 DELEGA UNIFICATA
04/11/2026;-12,00;SPESE TENUTA CONTO
05/11/2026;122,00;BONIFICO DA ROSSI SRL FATTURA 12
""".encode()


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    conto = Conto.objects.create(azienda=azienda, nome="Principale", iban=IBAN)
    RegolaMovimento.objects.create(azienda=azienda, nome="Banca", descrizione_contiene="commissioni|spese tenuta", categoria="Commissioni bancarie",
                                   codice_studio="61.05", importo_a=Decimal("50"))
    return {"azienda": azienda, "conto": conto}


def test_alla_importazione(s):
    abbina.importa(s["conto"], CSV, "estratto.csv")
    classificati = MovimentoBanca.objects.filter(stato=MovimentoBanca.CLASSIFICATO)
    assert sorted(classificati.values_list("importo", flat=True)) == [Decimal("-12.00"), Decimal("-2.50")]
    assert set(classificati.values_list("categoria", "codice_studio")) == {("Commissioni bancarie", "61.05")}
    assert MovimentoBanca.objects.filter(stato=MovimentoBanca.DA_ABBINARE).count() == 2      # F24 e l'incasso


def test_condizioni(s):
    r = RegolaMovimento(azienda=s["azienda"], nome="X", categoria="X", segno="entrate", controparte_contiene="rossi", importo_da=Decimal("100"))
    m = MovimentoBanca(importo=Decimal("150"), descrizione="", controparte="Rossi Srl")
    assert r.corrisponde(m)
    m.importo = Decimal("-150")
    assert not r.corrisponde(m)
    m.importo = Decimal("50")
    assert not r.corrisponde(m)
    with pytest.raises(ValidationError):
        RegolaMovimento(azienda=s["azienda"], nome="vuota", categoria="X").full_clean()


def test_a_mano_con_regola_e_ripristino(s):
    abbina.importa(s["conto"], CSV, "estratto.csv")
    f24 = MovimentoBanca.objects.get(importo=Decimal("-1500"))
    regola = classifica.classifica(f24, "F24", "", crea_regola=True)
    f24.refresh_from_db()
    assert f24.stato == "classificato" and regola.descrizione_contiene == "F24 DELEGA UNIFICATA" and regola.segno == "uscite"
    with pytest.raises(ValidationError):
        abbina.abbina(f24, ["p1"])                                                            # classificato: non si abbina
    abbina.ripristina(f24)
    f24.refresh_from_db()
    assert f24.stato == "da_abbinare" and f24.categoria == ""
    assert classifica.applica(s["azienda"]) == 1                                              # la regola nata lo riprende


def test_pagine_ed_export(client, s):
    root = User.objects.create_superuser("root", "r@x.it", "x")
    client.force_login(root)
    abbina.importa(s["conto"], CSV, "estratto.csv")
    html = client.get("/banca/riconcilia/").content.decode()
    assert "Classificalo" in html and "Applica le regole" in html and "Commissioni bancarie" in html
    f24 = MovimentoBanca.objects.get(importo=Decimal("-1500"))
    client.post(f"/banca/movimento/{f24.pk}/classifica/", {"categoria": "F24", "codice": "19.01"})
    f24.refresh_from_db()
    assert f24.categoria == "F24" and f24.codice_studio == "19.01" and not RegolaMovimento.objects.filter(categoria="F24").exists()
    assert client.get("/banca/regole/").status_code == 200
    from banca.per_commercialista import movimenti
    richiesta = type("R", (), {"user": root, "azienda": s["azienda"]})()
    file = dict(movimenti(richiesta, 2026, 11, []))
    sintesi = file["banca/movimenti-senza-fattura.csv"].decode("utf-8-sig")
    assert "Commissioni bancarie;61.05;-14,50" in sintesi and "F24;19.01;-1500,00" in sintesi
