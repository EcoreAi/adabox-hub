"""Team e obiettivi di vendita: risultati per persona e team con obiettivo, tasso di vittoria, durata media e motivi di
perdita; riassegnazione nel team a chi ha meno opportunità aperte; pagina."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from core.models import Azienda
from crm import risultati
from crm.models import MotivoPerdita, ObiettivoVendita, Opportunita, TeamVendita

OGGI = datetime.date.today()


@pytest.fixture
def s(db):
    from pathlib import Path

    from django.core.management import call_command

    import crm
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    anna, luca = User.objects.create_user("anna", first_name="Anna"), User.objects.create_user("luca")
    team = TeamVendita.objects.create(azienda=azienda, nome="Nord", responsabile=anna)
    team.membri.set([anna, luca])
    prezzo = MotivoPerdita.objects.create(nome="Prezzo")

    def opp(chi, stato, valore, giorni=10, motivo=None):
        o = Opportunita.objects.create(azienda=azienda, titolo=f"{chi} {valore}", commerciale=chi, valore_atteso=Decimal(valore))
        Opportunita.objects.filter(pk=o.pk).update(stato=stato, creata_il=OGGI - datetime.timedelta(days=giorni),
                                                   chiusa_il=OGGI if stato != "aperta" else None, motivo_perdita=motivo)
        return Opportunita.objects.get(pk=o.pk)
    opp(anna, "vinta", 1000, 20)
    opp(anna, "vinta", 500, 10)
    opp(anna, "persa", 800, 30, prezzo)
    opp(luca, "persa", 300, 5)
    opp(luca, "aperta", 2000)
    ObiettivoVendita.objects.create(azienda=azienda, utente=anna, dal=OGGI.replace(day=1), al=OGGI, importo=Decimal(3000))
    ObiettivoVendita.objects.create(azienda=azienda, team=team, dal=OGGI.replace(day=1), al=OGGI, importo=Decimal(6000))
    return {"azienda": azienda, "anna": anna, "luca": luca, "team": team}


def test_risultati(s):
    r = risultati.risultati(s["azienda"], OGGI.replace(day=1), OGGI)
    anna = next(x for x in r["persone"] if x["chi"] == s["anna"])
    assert (anna["vinto"], anna["vinte"], anna["perse"], anna["tasso"], anna["durata"], anna["raggiunto"]) == (Decimal(1500), 2, 1, 66, 20, 50)
    team, = r["team"]
    assert team["vinto"] == Decimal(1500) and team["raggiunto"] == 25 and team["tasso"] == 50
    assert r["motivi"][0] == {"motivo": "Prezzo", "n": 1} and r["totale"]["perse"] == 2


def test_team_del_commerciale_e_riassegnazione(s):
    o = Opportunita.objects.create(azienda=s["azienda"], titolo="Nuova", commerciale=s["luca"])
    assert o.team == s["team"]
    nuove = [Opportunita.objects.create(azienda=s["azienda"], titolo=f"N{i}") for i in range(3)]
    dati = risultati.riassegna_nel_team(nuove, s["team"])
    assert dati[s["anna"]] == 3                                            # Luca ha già 2 aperte, Anna nessuna


def test_pagina(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get("/crm/risultati/").content.decode()
    assert "Obiettivi e risultati" in html and "Prezzo" in html and "Nord" in html
