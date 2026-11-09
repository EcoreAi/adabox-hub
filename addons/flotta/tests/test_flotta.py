"""Parco auto: targa normalizzata, scadenze in arrivo e scadute, costi che aggiornano i km, canoni nell'anno, pagine."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from core.models import Azienda
from flotta.models import ContrattoVeicolo, CostoVeicolo, Veicolo, riepilogo_costi
from personale.models import Dipendente

OGGI = datetime.date.today()


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    mario = Dipendente.objects.create(azienda=azienda, nome="Mario", cognome="Rossi")
    v = Veicolo(azienda=azienda, targa="ab 123 cd", modello="Panda", assegnato_a=mario, km=10000,
                assicurazione_al=OGGI + datetime.timedelta(days=10), revisione_al=OGGI - datetime.timedelta(days=1), tagliando_km=10300)
    v.full_clean()
    v.save()
    return {"azienda": azienda, "v": v, "mario": mario}


def test_scadenze_costi_canoni(s):
    v = s["v"]
    assert v.targa == "AB123CD"
    nomi = {n: scaduta for n, _, scaduta in v.scadenze()}
    assert nomi == {"Assicurazione": False, "Revisione": True, "Tagliando ai km": False}
    CostoVeicolo.objects.create(azienda=s["azienda"], veicolo=v, tipo="carburante", importo=Decimal("60"), km=10450)
    v.refresh_from_db()
    assert v.km == 10450 and any(n == "Tagliando ai km" and sc for n, _, sc in v.scadenze())
    ContrattoVeicolo.objects.create(azienda=s["azienda"], veicolo=v, dal=datetime.date(OGGI.year, 1, 1), al=datetime.date(OGGI.year + 2, 12, 31),
                                    canone=Decimal("400"))
    r = riepilogo_costi(v)
    assert r["canoni"] == Decimal("4800") and r["totale"] == Decimal("4860")


def test_pagine(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    assert "Costi del" in client.get(f"/flotta/veicoli/{s['v'].pk}/").content.decode()
    assert "AB123CD" in client.get(f"/personale/dipendenti/{s['mario'].pk}/").content.decode()
    from flotta.riepilogo import voci
    richiesta = type("R", (), {"user": User.objects.get(username="root"), "azienda": s["azienda"]})()
    assert voci(richiesta, OGGI, OGGI)[0]["numero"] == 3
