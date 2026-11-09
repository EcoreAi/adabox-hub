"""Analitica: imputazione (sostituire, aggiungere una parte, oltre il 100%), modelli di ripartizione, report per asse con
il non imputato, budget con consuntivo e proiezione, pagine e sezione sui documenti."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from analitica import fonti, operazioni
from analitica.models import Asse, Budget, Imputazione, ModelloRipartizione, RigaBudget, RigaModello, Voce
from contatti.models import Contatto
from core.models import Azienda
from fatturazione.models import Fattura, RigaFattura

OGGI = datetime.date.today()


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi", cliente=True)
    f = Fattura.objects.create(azienda=azienda, cliente=cliente, numero="1", data=OGGI)
    r1 = RigaFattura.objects.create(fattura=f, descrizione="Sviluppo", quantita=1, prezzo=Decimal("1000"))
    r2 = RigaFattura.objects.create(fattura=f, descrizione="Hosting", quantita=1, prezzo=Decimal("200"))
    Fattura.objects.filter(pk=f.pk).update(stato=Fattura.EMESSA)
    asse = Asse.objects.create(azienda=azienda, nome="Centro di costo")
    web = Voce.objects.create(azienda=azienda, asse=asse, codice="WEB", nome="Siti")
    infra = Voce.objects.create(azienda=azienda, asse=asse, codice="INF", nome="Infrastruttura")
    return {"azienda": azienda, "f": f, "r1": r1, "r2": r2, "asse": asse, "web": web, "infra": infra, "fonte": fonti.per_chiave("fatture")}


def test_imputa_e_report(s):
    operazioni.imputa(s["azienda"], s["fonte"], [s["r1"].pk], s["web"])
    operazioni.imputa(s["azienda"], s["fonte"], [s["r2"].pk], s["web"], Decimal(50))
    operazioni.imputa(s["azienda"], s["fonte"], [s["r2"].pk], s["infra"], Decimal(30), sostituisci=False)
    with pytest.raises(ValidationError, match="100%"):
        operazioni.imputa(s["azienda"], s["fonte"], [s["r2"].pk], s["infra"], Decimal(60), sostituisci=False)
    r = operazioni.report(s["azienda"], s["asse"])
    per_voce = {x["voce"].codice: x["ricavi"] for x in r["righe"]}
    assert per_voce == {"WEB": Decimal("1100.00"), "INF": Decimal("60.00")}
    assert r["non_imputato"][0]["importo"] == Decimal("40.00")                    # 20% di 200
    operazioni.imputa(s["azienda"], s["fonte"], [s["r2"].pk], s["infra"])        # sostituisce le parti sull'asse
    assert list(Imputazione.objects.filter(id_riga=s["r2"].pk).values_list("voce__codice", "percentuale")) == [("INF", Decimal(100))]


def test_modello(s):
    m = ModelloRipartizione.objects.create(azienda=s["azienda"], nome="Metà e metà")
    RigaModello.objects.create(modello=m, voce=s["web"], percentuale=50)
    RigaModello.objects.create(modello=m, voce=s["infra"], percentuale=50)
    operazioni.applica_modello(s["azienda"], s["fonte"], [s["r1"].pk, s["r2"].pk], m)
    r = operazioni.report(s["azienda"], s["asse"])
    assert {x["voce"].codice: x["ricavi"] for x in r["righe"]} == {"WEB": Decimal("600.00"), "INF": Decimal("600.00")}
    RigaModello.objects.create(modello=m, voce=s["web"], percentuale=10)
    with pytest.raises(ValidationError, match="100"):
        operazioni.applica_modello(s["azienda"], s["fonte"], [s["r1"].pk], m)


def test_budget(s):
    operazioni.imputa(s["azienda"], s["fonte"], [s["r1"].pk, s["r2"].pk], s["web"])
    b = Budget.objects.create(azienda=s["azienda"], voce=s["web"], dal=OGGI - datetime.timedelta(days=9), al=OGGI + datetime.timedelta(days=10))
    RigaBudget.objects.create(budget=b, categoria="ricavi", importo=Decimal("2000"))
    c = operazioni.confronto(b)
    ricavi, = c["righe"]
    assert ricavi["consuntivo"] == Decimal("1200.00") and ricavi["percentuale"] == 60 and ricavi["proiezione"] == Decimal("2400.00")
    assert c["avanzamento"] == 50


def test_pagine(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get("/analitica/imputa/?fonte=fatture").content.decode()
    assert "Sviluppo" in html and "Hosting" in html
    client.post("/analitica/imputa/", {"fonte": "fatture", "riga": [s["r1"].pk], "voce": s["web"].pk, "percentuale": "100"})
    assert Imputazione.objects.get().voce == s["web"]
    assert "Siti" in client.get(f"/fatturazione/fatture/{s['f'].pk}/").content.decode()
    html = client.get(f"/analitica/report/?asse={s['asse'].pk}").content.decode()
    assert "1000,00" in html or "1.000,00" in html
    assert "Margine" in client.get(f"/analitica/report/?asse={s['asse'].pk}&formato=csv").content.decode("utf-8-sig")
    client.post("/analitica/imputa/", {"fonte": "fatture", "riga": [s["r1"].pk], "azione": "togli", "asse": s["asse"].pk})
    assert not Imputazione.objects.exists()
    b = Budget.objects.create(azienda=s["azienda"], voce=s["web"], dal=OGGI, al=OGGI)
    assert "Previsto e consuntivo" in client.get(f"/analitica/budget/{b.pk}/").content.decode()
