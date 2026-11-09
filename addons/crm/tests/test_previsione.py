"""Previsione delle vendite per mese: vinto più pipeline aperta ponderata, scadute e senza data nel mese corrente,
filtro per commerciale, rettifica manuale che sostituisce la calcolata."""
import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import call_command

import crm
from core.models import Azienda
from crm import previsione
from crm.models import Opportunita, RettificaPrevisione

OGGI = datetime.date(2026, 3, 15)


@pytest.fixture
def s(db):
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    anna, luca = User.objects.create_user("anna"), User.objects.create_user("luca")

    def opp(valore, probabilita=0, chiusura=None, stato=Opportunita.APERTA, chiusa_il=None, chi=anna):
        o = Opportunita.objects.create(azienda=azienda, titolo=f"Opp {valore}", commerciale=chi)
        Opportunita.objects.filter(pk=o.pk).update(valore_atteso=D(valore), probabilita=probabilita, stato=stato,   # senza la fase
                                                   chiusura_prevista=chiusura, chiusa_il=chiusa_il)
    opp("1000", 50, datetime.date(2026, 3, 20))                                   # questo mese: 500
    opp("2000", 10, datetime.date(2026, 1, 10))                                   # scaduta: conta ora, 200
    opp("400", 25)                                                                # senza data: conta ora, 100
    opp("3000", 20, datetime.date(2026, 5, 5), chi=luca)                          # maggio: 600
    opp("700", stato=Opportunita.VINTA, chiusa_il=datetime.date(2026, 3, 2))      # vinta questo mese
    opp("900", stato=Opportunita.VINTA, chiusa_il=datetime.date(2026, 2, 27))     # vinta il mese scorso: fuori
    opp("5000", 90, datetime.date(2026, 3, 25), stato=Opportunita.PERSA)          # persa: fuori
    return {"azienda": azienda, "anna": anna, "luca": luca}


def test_mesi_con_vinto_e_pipeline_ponderata(s):
    righe, totale = previsione.previsione(s["azienda"], oggi=OGGI)
    assert [r["mese"] for r in righe] == [datetime.date(2026, m, 1) for m in range(3, 9)]
    marzo, aprile, maggio = righe[:3]
    assert (marzo["vinto"], marzo["pipeline"], marzo["ponderato"], marzo["calcolata"], marzo["aperte"]) == (
        D("700"), D("3400"), D("800"), D("1500"), 3)
    assert aprile["calcolata"] == 0 and maggio["ponderato"] == D("600")
    assert totale["previsione"] == D("2100")


def test_per_commerciale(s):
    righe, totale = previsione.previsione(s["azienda"], utente=s["luca"], oggi=OGGI)
    assert righe[0]["calcolata"] == 0 and righe[2]["ponderato"] == D("600") and totale["previsione"] == D("600")


def test_cambio_d_anno():
    assert previsione.piu_mesi(datetime.date(2026, 11, 1), 3) == datetime.date(2027, 2, 1)


def test_rettifica_sostituisce_la_calcolata_e_si_toglie(s):
    previsione.rettifica(s["azienda"], datetime.date(2026, 4, 17), D("999"), nota="Gara in arrivo")
    r = RettificaPrevisione.objects.get()
    assert r.mese == datetime.date(2026, 4, 1) and r.utente is None             # il mese si normalizza al primo
    righe, totale = previsione.previsione(s["azienda"], oggi=OGGI)
    assert (righe[1]["calcolata"], righe[1]["previsione"]) == (D(0), D("999")) and totale["previsione"] == D("3099")
    assert previsione.previsione(s["azienda"], utente=s["anna"], oggi=OGGI)[0][1]["previsione"] == D(0)   # vale per l'azienda
    previsione.rettifica(s["azienda"], datetime.date(2026, 4, 1), D("1200"))     # la stessa riga, aggiornata
    assert RettificaPrevisione.objects.get().importo == D("1200")
    previsione.rettifica(s["azienda"], datetime.date(2026, 4, 1), None)
    assert not RettificaPrevisione.objects.exists()


def test_pagina_e_rettifica_all_italiana(client, superuser, s):
    assert client.get("/crm/previsione/").status_code == 200
    mese = datetime.date.today().replace(day=1)
    r = client.post("/crm/previsione/", {"mese": mese.isoformat(), "importo": "12.000,50", "nota": "a mano"})
    assert r.status_code == 302 and RettificaPrevisione.objects.get().importo == D("12000.50")
    client.post("/crm/previsione/", {"mese": mese.isoformat(), "importo": ""})                   # vuoto: la toglie
    assert not RettificaPrevisione.objects.exists()


def test_solo_chi_ha_il_permesso_rettifica(client, s):
    s["anna"].user_permissions.add(Permission.objects.get(codename="view_opportunita"))
    s["anna"].profilo.aziende.set([s["azienda"]])
    client.force_login(s["anna"])
    assert client.get("/crm/previsione/").status_code == 200
    client.post("/crm/previsione/", {"mese": datetime.date.today().replace(day=1).isoformat(), "importo": "100"})
    assert not RettificaPrevisione.objects.exists()
