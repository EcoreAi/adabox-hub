import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.core.management import call_command

import progetti
import timesheet
from core.models import Azienda
from core.registry import manifest
from core.registry.groups import crea_gruppi
from progetti.models import Compito, Progetto
from timesheet.models import RigaOre

LUNEDI = datetime.date(2026, 10, 26)


@pytest.fixture
def scena(db):
    call_command("loaddata", str(Path(progetti.__file__).parent / "data" / "fasi.json"), verbosity=0)
    for app in (progetti, timesheet):
        crea_gruppi(manifest.leggi(Path(app.__file__).parent))
    azienda = Azienda.objects.get(pk=1)
    utenti = {}
    for nome in ("ada", "bea"):
        u = User.objects.create_user(nome, f"{nome}@example.com", "x")
        u.groups.add(Group.objects.get(name="Progetti / Utente"), Group.objects.get(name="Timesheet / Utente"))
        utenti[nome] = User.objects.get(pk=u.pk)
    sito = Progetto.objects.create(azienda=azienda, nome="Sito", responsabile=utenti["ada"])
    sito.membri.add(utenti["bea"])
    home = Compito.objects.create(azienda=azienda, progetto=sito, titolo="Home", ore_previste=Decimal("10"))
    home.assegnatari.add(utenti["ada"])
    altro = Progetto.objects.create(azienda=azienda, nome="Altro")
    return utenti, sito, home, altro


def _riga(utente, progetto, ore, data=LUNEDI, compito=None):
    return RigaOre.objects.create(azienda=progetto.azienda, utente=utente, progetto=progetto, compito=compito,
                                  ore=Decimal(ore), data=data)


def test_validazioni(scena):
    utenti, sito, home, altro = scena
    with pytest.raises(ValidationError) as e:
        RigaOre(azienda=sito.azienda, utente=utenti["ada"], progetto=altro, compito=home, ore=Decimal(2), data=LUNEDI).full_clean()
    assert "compito" in e.value.message_dict
    _riga(utenti["ada"], sito, "20")
    with pytest.raises(ValidationError) as e:
        RigaOre(azienda=sito.azienda, utente=utenti["ada"], progetto=sito, ore=Decimal(5), data=LUNEDI).full_clean()
    assert "superano 24" in str(e.value)


def test_ognuno_vede_le_sue_ore(client, scena):
    utenti, sito, home, _ = scena
    _riga(utenti["ada"], sito, "2")
    _riga(utenti["bea"], sito, "3")
    client.force_login(utenti["bea"])
    r = client.get("/timesheet/ore/")
    assert [str(o.ore) for o, _ in r.context["righe"]] == ["3.00"]
    responsabile = utenti["ada"]
    responsabile.user_permissions.add(Permission.objects.get(codename="vedi_tutte_ore"))
    client.force_login(User.objects.get(pk=responsabile.pk))
    r = client.get("/timesheet/ore/")
    assert len(r.context["righe"]) == 2 and r.context["totali"][5] == "5,00"


def test_form_registra_per_se(client, scena):
    utenti, sito, home, altro = scena
    client.force_login(utenti["bea"])
    form = client.get("/timesheet/ore/nuovo/").context["form"]
    assert "utente" not in form.fields and list(form.fields["progetto"].queryset) == [sito]
    r = client.post("/timesheet/ore/nuovo/", {"data": "2026-10-27", "ore": "1,5".replace(",", "."), "progetto": sito.pk,
                                              "compito": home.pk, "fatturabile": "on"})
    assert r.status_code == 302
    assert RigaOre.objects.get().utente == utenti["bea"]


def test_sezioni_su_progetto_e_compito(client, scena):
    utenti, sito, home, _ = scena
    _riga(utenti["ada"], sito, "4", compito=home)
    client.force_login(utenti["ada"])
    pagina = client.get(f"/progetti/progetti/{sito.pk}/").content.decode()
    assert "4,00 h registrate" in pagina
    html = client.get(f"/progetti/compiti/{home.pk}/").content.decode()
    assert "4,00 h registrate su 10,00 h previste" in html and "width: 40%" in html


def test_settimana(client, scena):
    utenti, sito, home, _ = scena
    _riga(utenti["ada"], sito, "1", data=LUNEDI, compito=home)
    _riga(utenti["ada"], sito, "2", data=LUNEDI, compito=home)
    client.force_login(utenti["ada"])
    r = client.get("/timesheet/settimana/", {"data": "2026-10-28"})
    assert r.context["lunedi"] == LUNEDI
    (riga,) = r.context["righe"]
    assert riga["celle"][0]["valore"] == Decimal("3.00") and riga["totale"] == Decimal("3.00")
    dati = {"data": LUNEDI.isoformat(), f"ore_{home.pk}_{LUNEDI.isoformat()}": "2,5",
            f"ore_{home.pk}_{(LUNEDI + datetime.timedelta(days=1)).isoformat()}": "4"}
    assert client.post("/timesheet/settimana/", dati).status_code == 302
    righe = list(RigaOre.objects.filter(utente=utenti["ada"]).order_by("data").values_list("data", "ore"))
    assert righe == [(LUNEDI, Decimal("2.50")), (LUNEDI + datetime.timedelta(days=1), Decimal("4.00"))]


def test_settimana_errori(client, scena):
    utenti, sito, home, _ = scena
    client.force_login(utenti["ada"])
    r = client.post("/timesheet/settimana/", {"data": LUNEDI.isoformat(), f"ore_{home.pk}_{LUNEDI.isoformat()}": "30"})
    assert r.status_code == 200 and not RigaOre.objects.exists()


def test_viste(client, scena):
    utenti, sito, _, _ = scena
    _riga(utenti["ada"], sito, "2")
    client.force_login(utenti["ada"])
    for url in ("/timesheet/ore/grafico/?misura=sum:ore", "/timesheet/ore/calendario/?mese=2026-10",
                "/timesheet/ore/?g=progetto", "/timesheet/ore/esporta/?formato=csv"):
        assert client.get(url).status_code == 200, url
