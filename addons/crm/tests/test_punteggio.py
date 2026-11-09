"""Punteggio predittivo: impara dallo storico vinte e perse, spiega i fattori, resta vuoto con poco storico,
ordina il kanban e si mostra nella scheda."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

import crm
from core.models import Azienda
from crm import punteggio
from crm.models import Opportunita

OGGI = datetime.date.today()


@pytest.fixture
def s(db):
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    anna, luca = User.objects.create_user("anna", first_name="Anna"), User.objects.create_user("luca", first_name="Luca")

    def opp(chi, stato, origine, telefono=""):
        o = Opportunita.objects.create(azienda=azienda, titolo=f"{chi} {origine}", commerciale=chi, origine=origine,
                                       telefono=telefono, valore_atteso=Decimal(5000))
        if stato != "aperta":
            Opportunita.objects.filter(pk=o.pk).update(stato=stato, chiusa_il=OGGI)
        return o
    return {"azienda": azienda, "anna": anna, "luca": luca, "opp": opp}


def test_poco_storico_niente_punteggio(s):
    o = s["opp"](s["anna"], "aperta", "Fiera")
    punteggio.ricalcola()
    o.refresh_from_db()
    assert o.punteggio is None and "Storico insufficiente" in o.punteggio_fattori[0]["fattore"]


def test_impara_da_vinte_e_perse(s):
    opp, anna, luca = s["opp"], s["anna"], s["luca"]
    for _ in range(6):
        opp(anna, "vinta", "Passaparola: cliente", "333")      # il passaparola di Anna vince
    for _ in range(6):
        opp(luca, "persa", "Modulo del sito: Contatti")         # i moduli del sito di Luca si perdono
    opp(anna, "persa", "Passaparola")
    opp(luca, "vinta", "Modulo del sito")
    buona = opp(anna, "aperta", "Passaparola", "347")
    scarsa = opp(luca, "aperta", "Modulo del sito: Contatti")
    assert punteggio.ricalcola(s["azienda"].pk) == 2
    buona.refresh_from_db()
    scarsa.refresh_from_db()
    assert buona.punteggio > 80 > 20 > scarsa.punteggio
    fattori = {f["fattore"]: f["effetto"] for f in buona.punteggio_fattori}
    assert fattori["Origine: Passaparola"] > 0 and fattori["Commerciale: Anna"] > 0
    assert any(f["effetto"] < 0 for f in scarsa.punteggio_fattori)
    # le chiuse non hanno punteggio
    assert not Opportunita.objects.exclude(stato="aperta").exclude(punteggio=None).exists()


def test_kanban_e_scheda(s, client):
    for i in range(12):
        s["opp"](s["anna"], "vinta" if i % 2 else "persa", "Fiera")
    o = s["opp"](s["anna"], "aperta", "Fiera")
    punteggio.ricalcola()
    root = User.objects.create_superuser("root", "r@x.it", "x")
    client.force_login(root)
    r = client.get(f"/crm/opportunita/{o.pk}/")
    assert r.status_code == 200 and "Punteggio" in r.content.decode()
    r = client.get("/crm/opportunita/kanban/?ordine=-punteggio")
    assert r.status_code == 200 and "Punteggio" in r.content.decode()
