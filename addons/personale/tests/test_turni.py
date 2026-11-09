"""Turni: griglia settimanale, ore oltre il contratto, assenza in turno segnalata, copia della settimana, turni nel profilo."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission, User

from core.models import Azienda
from personale import turni
from personale.models import AssegnazioneTurno, Assenza, Dipendente, TipoAssenza, TurnoLavoro

LUN = turni.lunedi()


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    u = User.objects.create_user("mario")
    u.user_permissions.add(Permission.objects.get(codename="add_assenza"))
    mario = Dipendente.objects.create(azienda=azienda, nome="Mario", cognome="Rossi", ore_settimanali=Decimal(16), utente=u)
    lungo = TurnoLavoro.objects.create(azienda=azienda, nome="Giornata", inizio=datetime.time(8), fine=datetime.time(17), pausa_minuti=60)
    notte = TurnoLavoro.objects.create(azienda=azienda, nome="Notte", inizio=datetime.time(22), fine=datetime.time(6))
    return {"azienda": azienda, "mario": mario, "lungo": lungo, "notte": notte, "u": u}


def test_griglia_e_copia(client, s):
    assert s["lungo"].ore == 8 and s["notte"].ore == 8
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    m = s["mario"]
    dati = {f"t_{m.pk}_{(LUN + datetime.timedelta(days=i)).isoformat()}": s["lungo"].pk for i in range(3)}
    client.post("/personale/turni/", {"settimana": LUN.isoformat(), **dati})
    assert AssegnazioneTurno.objects.filter(dipendente=m).count() == 3
    giorni, righe = turni.settimana(s["azienda"], LUN, [m])
    assert righe[0]["ore"] == Decimal("24.0") and righe[0]["oltre"]
    tipo = TipoAssenza.objects.create(nome="Ferie")
    Assenza.objects.create(azienda=s["azienda"], dipendente=m, tipo=tipo, dal=LUN, al=LUN, stato=Assenza.APPROVATA)
    _, righe = turni.settimana(s["azienda"], LUN, [m])
    assert righe[0]["celle"][0]["conflitto"]
    prossima = LUN + datetime.timedelta(days=7)
    client.post("/personale/turni/", {"settimana": prossima.isoformat(), "azione": "copia"})
    assert AssegnazioneTurno.objects.filter(dipendente=m, data__gte=prossima).count() == 3
    assert "Copia dalla settimana prima" in client.get("/personale/turni/").content.decode()


def test_nel_profilo(client, s):
    AssegnazioneTurno.objects.create(azienda=s["azienda"], dipendente=s["mario"], data=datetime.date.today(), turno=s["notte"])
    client.force_login(s["u"])
    assert "I miei turni" in client.get("/personale/profilo/").content.decode()
