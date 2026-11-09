"""Contratti di lavoro: quello in vigore aggiorna orario e ferie del dipendente, sovrapposizioni vietate, determinato con
scadenza, avviso dei contratti in scadenza senza rinnovo, giro del mattino, pagine riservate."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError

from core.models import Azienda
from personale import contratti
from personale.models import ContrattoLavoro, Dipendente

OGGI = datetime.date.today()


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    mario = Dipendente.objects.create(azienda=azienda, nome="Mario", cognome="Rossi", data_assunzione=OGGI.replace(year=OGGI.year - 1))
    return {"azienda": azienda, "mario": mario}


def test_in_vigore_aggiorna_il_dipendente(s):
    c = ContrattoLavoro.objects.create(azienda=s["azienda"], dipendente=s["mario"], tipo="determinato", dal=OGGI - datetime.timedelta(days=10),
                                       al=OGGI + datetime.timedelta(days=20), ore_settimanali=Decimal(30), giorni_ferie_annui=Decimal(20),
                                       retribuzione_annua=Decimal(26000), mensilita=13)
    s["mario"].refresh_from_db()
    assert s["mario"].ore_settimanali == 30 and s["mario"].giorni_ferie_annui == 20 and s["mario"].tipo_contratto == "determinato"
    assert contratti.in_vigore(s["mario"]) == c and c.mensile == Decimal("2000.00")
    with pytest.raises(ValidationError, match="sovrappone"):
        ContrattoLavoro(azienda=s["azienda"], dipendente=s["mario"], dal=OGGI).full_clean()
    with pytest.raises(ValidationError, match="scadenza"):
        ContrattoLavoro(azienda=s["azienda"], dipendente=s["mario"], tipo="determinato", dal=OGGI + datetime.timedelta(days=40)).full_clean()


def test_scadenze_e_giro(s):
    c = ContrattoLavoro.objects.create(azienda=s["azienda"], dipendente=s["mario"], tipo="determinato", dal=OGGI - datetime.timedelta(days=100),
                                       al=OGGI + datetime.timedelta(days=15))
    assert contratti.in_scadenza(ContrattoLavoro.objects.all()) == [c]
    rinnovo = ContrattoLavoro.objects.create(azienda=s["azienda"], dipendente=s["mario"], tipo="indeterminato", dal=c.al + datetime.timedelta(days=1),
                                             ore_settimanali=Decimal(40))
    assert contratti.in_scadenza(ContrattoLavoro.objects.all()) == []          # c'è il rinnovo
    s["mario"].refresh_from_db()
    assert s["mario"].tipo_contratto == "determinato"                           # il rinnovo non è ancora in vigore
    assert contratti.allinea(s["mario"], rinnovo.dal) and s["mario"].tipo_contratto == "indeterminato"


def test_pagine_riservate(client, s):
    ContrattoLavoro.objects.create(azienda=s["azienda"], dipendente=s["mario"], dal=OGGI, retribuzione_annua=Decimal(30000))
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get(f"/personale/dipendenti/{s['mario'].pk}/").content.decode()
    assert "Contratti" in html and "Nuovo contratto" in html
    assert client.get("/personale/contratti/").status_code == 200
    capo = User.objects.create_user("capo")
    capo.user_permissions.add(Permission.objects.get(codename="view_dipendente"))
    client.force_login(capo)
    assert "Nuovo contratto" not in client.get(f"/personale/dipendenti/{s['mario'].pk}/").content.decode()
    assert client.get("/personale/contratti/").status_code == 403
