"""Fatturazione a tappe e acconti a corpo, costi esterni dall'analitica, budget e portafoglio."""
import datetime
from decimal import Decimal as D

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from commesse import operazioni
from commesse.models import Condizioni, Tappa
from commesse.tests.test_commesse import scena  # noqa: F401
from fatturazione.models import Fattura


def test_acconti_a_corpo(scena):  # noqa: F811
    c = scena["condizioni"]
    c.tipo, c.importo_corpo = Condizioni.CORPO, D(10000)
    c.save()
    acconto = operazioni.fattura_corpo(scena["progetto"], D(3000))
    assert acconto.imponibile == D(3000) and acconto.righe.get().descrizione.startswith("Acconto")
    assert operazioni.residuo_corpo(scena["progetto"]) == D(7000)
    with pytest.raises(ValidationError, match="Restano da fatturare 7000"):
        operazioni.fattura_corpo(scena["progetto"], D(8000))
    saldo = operazioni.fattura_corpo(scena["progetto"])
    assert saldo.imponibile == D(7000) and saldo.righe.get().descrizione.startswith("Saldo")
    with pytest.raises(ValidationError, match="per intero"):
        operazioni.fattura_corpo(scena["progetto"])
    acconto.stato = Fattura.ANNULLATA
    acconto.save()
    assert operazioni.residuo_corpo(scena["progetto"]) == D(3000)


def test_tappe(client, scena):  # noqa: F811
    c = scena["condizioni"]
    c.tipo, c.importo_corpo = Condizioni.TAPPE, D(10000)
    c.save()
    analisi = Tappa.objects.create(condizioni=c, nome="Analisi", percentuale=D(30))
    rilascio = Tappa.objects.create(condizioni=c, nome="Rilascio", importo=D(7000))
    with pytest.raises(ValidationError):
        Tappa(condizioni=c, nome="Doppia", percentuale=D(10), importo=D(5)).full_clean()
    r = operazioni.redditivita(scena["progetto"])
    assert r["in_attesa"] == D(10000) and [t.nome for t in r["tappe"]] == ["Analisi", "Rilascio"]
    f = operazioni.completa_tappa(analisi)
    analisi.refresh_from_db()
    assert f.imponibile == D(3000) and analisi.fattura == f and analisi.completata_il == datetime.date.today()
    with pytest.raises(ValidationError, match="già"):
        operazioni.completa_tappa(analisi)
    Tappa.objects.create(condizioni=c, nome="Extra", importo=D(500))
    with pytest.raises(ValidationError, match="più del valore"):
        operazioni.completa_tappa(rilascio)
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get(f"/progetti/progetti/{scena['progetto'].pk}/").content.decode()
    assert "Completata: fattura" in html and "Analisi" in html


def test_costi_esterni_budget_e_portafoglio(client, scena):  # noqa: F811
    from analitica import fonti, operazioni as an
    from analitica.models import Asse, Budget, RigaBudget, Voce
    from contatti.models import Contatto
    from sdi.models import FatturaPassiva, RigaPassiva
    azienda, progetto = scena["azienda"], scena["progetto"]
    asse = Asse.objects.create(azienda=azienda, nome="Commessa")
    voce = Voce.objects.create(azienda=azienda, asse=asse, nome="Portale", progetto_id=progetto.pk)
    fornitore = Contatto.objects.create(azienda=azienda, nome="Studio grafico", fornitore=True)
    fp = FatturaPassiva.objects.create(azienda=azienda, fornitore=fornitore, numero="7", data=datetime.date.today(), totale=D(1220),
                                       imponibile=D(1000), imposta=D(220))
    riga = RigaPassiva.objects.create(fattura=fp, descrizione="Grafica", quantita=1, prezzo=1000, importo=D(1000), aliquota=22)
    an.imputa(azienda, fonti.per_chiave("passive"), [riga.pk], voce)
    r = operazioni.redditivita(progetto)
    assert r["esterni"] == D("1000.00") and r["margine"] == r["ricavi"] - r["costo"] - D(1000)
    b = Budget.objects.create(azienda=azienda, voce=voce, dal=datetime.date.today().replace(day=1), al=datetime.date.today().replace(day=28))
    RigaBudget.objects.create(budget=b, categoria="acquisti", importo=D(800))
    assert operazioni.redditivita(progetto)["budget"]["budget"] == b
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get("/commesse/portafoglio/").content.decode()
    assert "Portale" in html and "Portafoglio progetti" in html
