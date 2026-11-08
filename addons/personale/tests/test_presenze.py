"""HR-03: timbrature dal chiosco (badge o PIN, con blocco dopo troppi errori) e dal web, ore lavorate rispetto alle
previste con assenze e anomalie, export del mese per il consulente, correzioni a mano con motivo; ratei e riporto."""
import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.management import call_command

import personale
from core import parametri
from core.models import Azienda
from personale import presenze, saldi
from personale.models import Assenza, Dipendente, Timbratura, TipoAssenza

ROMA = ZoneInfo("Europe/Rome")


def _alle(giorno, ora, minuti=0):
    return datetime.datetime(giorno.year, giorno.month, giorno.day, ora, minuti, tzinfo=ROMA)


@pytest.fixture
def s(db):
    cache.clear()
    call_command("loaddata", str(Path(personale.__file__).parent / "data" / "tipi.json"), verbosity=0)
    az = Azienda.objects.get(pk=1)
    chiosco = User.objects.create_user("chiosco", "k@example.com", "x")
    chiosco.user_permissions.add(Permission.objects.get(codename="add_timbratura"))
    chiosco.profilo.aziende.set([az])
    chiosco.profilo.azienda_predefinita = az
    chiosco.profilo.save()
    mario_u = User.objects.create_user("mario", "m@example.com", "x")
    mario_u.profilo.aziende.set([az])
    mario = Dipendente.objects.create(azienda=az, nome="Mario", cognome="Rossi", utente=mario_u, badge="B-0001",
                                      data_assunzione=datetime.date(2020, 1, 1), ore_settimanali=Decimal(40))
    luca = Dipendente.objects.create(azienda=az, nome="Luca", cognome="Bianchi", data_assunzione=datetime.date(2020, 1, 1))
    return {"az": az, "chiosco": User.objects.get(pk=chiosco.pk), "mario": mario, "mario_u": mario_u, "luca": luca}


def test_pin_unico_e_riconoscimento(s):
    presenze.imposta_pin(s["mario"], "1234")
    with pytest.raises(ValueError, match="già usato"):
        presenze.imposta_pin(s["luca"], "1234")
    with pytest.raises(ValueError, match="4–8 cifre"):
        presenze.imposta_pin(s["luca"], "12a")
    assert "1234" not in Dipendente.objects.get(pk=s["mario"].pk).pin_impronta
    assert presenze.riconosci(s["az"], "1234", "k") == s["mario"] and presenze.riconosci(s["az"], "B-0001", "k") == s["mario"]
    for _ in range(presenze.TENTATIVI):
        assert presenze.riconosci(s["az"], "9999", "k") is None
    assert presenze.bloccato("k") and presenze.riconosci(s["az"], "1234", "k") is None      # bloccato anche col PIN giusto


def test_chiosco(client, s):
    presenze.imposta_pin(s["mario"], "4321")
    client.force_login(s["chiosco"])
    r = client.post("/personale/timbra/", {"codice": "4321"})
    assert "Ciao Mario" in r.content.decode() and 'value="entrata"' in r.content.decode()
    client.post("/personale/timbra/", {"codice": "4321", "verso": "entrata"})
    t = Timbratura.objects.get()
    assert t.dipendente == s["mario"] and t.verso == "entrata" and t.fonte == "chiosco"
    assert presenze.prossimo_verso(s["mario"]) == "uscita"
    assert client.post("/personale/timbra/", {"codice": "0000"}, follow=True).content.decode().count("non riconosciuto") == 1


def test_timbratura_dal_web(client, s):
    client.force_login(s["mario_u"])
    client.post("/personale/timbra/io/")
    client.post("/personale/timbra/io/")
    assert list(Timbratura.objects.order_by("il").values_list("verso", "fonte")) == [("entrata", "web"), ("uscita", "web")]


def test_giornate_e_anomalie(s):
    m = s["mario"]
    lun, mar, mer = datetime.date(2026, 10, 5), datetime.date(2026, 10, 6), datetime.date(2026, 10, 7)
    for verso, ora in (("entrata", 8), ("uscita", 12), ("entrata", 13), ("uscita", 18)):
        Timbratura.objects.create(azienda=s["az"], dipendente=m, verso=verso, il=_alle(lun, ora))
    Timbratura.objects.create(azienda=s["az"], dipendente=m, verso="entrata", il=_alle(mar, 9))
    ferie = TipoAssenza.objects.get(saldo="ferie")
    Assenza.objects.create(azienda=s["az"], dipendente=m, tipo=ferie, dal=mer, al=mer, stato="approvata")
    g = presenze.giornata(m, lun)
    assert g["lavorate"] == Decimal("9.00") and g["previste"] == Decimal("8.00") and g["differenza"] == Decimal("1.00") and not g["anomalia"]
    assert "manca l'uscita" in presenze.giornata(m, mar)["anomalia"]
    feriale = presenze.giornata(m, mer)
    assert feriale["previste"] == 0 and "Ferie" in feriale["assenza"] and not feriale["anomalia"]
    assert "nessuna timbratura" in presenze.giornata(m, datetime.date(2026, 10, 8))["anomalia"]
    assert presenze.giornata(m, datetime.date(2026, 10, 10))["previste"] == 0                # sabato


def test_riepilogo_ed_export(client, s):
    from openpyxl import load_workbook
    lun = datetime.date(2026, 10, 5)
    Timbratura.objects.create(azienda=s["az"], dipendente=s["mario"], verso="entrata", il=_alle(lun, 8))
    Timbratura.objects.create(azienda=s["az"], dipendente=s["mario"], verso="uscita", il=_alle(lun, 16))
    righe = presenze.riepilogo(s["az"], 2026, 10)
    mario = next(r for r in righe if r["dipendente"] == s["mario"])
    assert mario["lavorate"] == Decimal("8.00") and mario["anomalie"] > 0
    capo = User.objects.create_superuser("capo", "c@example.com", "x")
    capo.profilo.aziende.set([s["az"]])
    client.force_login(capo)
    assert "Rossi Mario" in client.get("/personale/presenze/?mese=2026-10").content.decode()
    r = client.get("/personale/presenze/?mese=2026-10&formato=xlsx")
    foglio = load_workbook(BytesIO(r.content)).active
    valori = [[c.value for c in riga] for riga in foglio.iter_rows()]
    assert valori[0][:3] == ["Dipendente", "Codice fiscale", "Data"]
    assert any(v[0] == "Rossi Mario" and v[2] == "05/10/2026" and v[4] == 8.0 for v in valori)


def test_correzione_a_mano_con_motivo(client, s):
    capo = User.objects.create_superuser("capo", "c@example.com", "x")
    capo.profilo.aziende.set([s["az"]])
    client.force_login(capo)
    dati = {"dipendente": s["mario"].pk, "verso": "uscita", "il": "2026-10-06 18:00", "nota": ""}
    client.post("/personale/timbrature/nuovo/", dati)
    assert not Timbratura.objects.exists()
    client.post("/personale/timbrature/nuovo/", {**dati, "nota": "dimenticata"})
    t = Timbratura.objects.get()
    assert t.fonte == "manuale" and t.inserita_da == capo


def test_ratei_e_riporto(s):
    m = s["mario"]
    assert saldi.maturate(m, 2026, datetime.date(2026, 3, 15))["ferie"] == Decimal("6.50")      # 3/12 di 26
    assert saldi.saldo(m, 2026)["ferie"]["riporto"] == 0                                          # spento di default
    parametri.scrivi("personale.riporto_dal", 2025, s["az"])
    ferie = TipoAssenza.objects.get(saldo="ferie")
    Assenza.objects.create(azienda=s["az"], dipendente=m, tipo=ferie, dal=datetime.date(2025, 8, 4),
                           al=datetime.date(2025, 8, 8), stato="approvata")                       # 5 giorni nel 2025
    s26 = saldi.saldo(m, 2026)["ferie"]
    assert s26["riporto"] == Decimal("21.00") and s26["residue"] == Decimal("47.00")
