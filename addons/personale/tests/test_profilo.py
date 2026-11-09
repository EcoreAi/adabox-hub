"""Il mio profilo: saldi, contratto, documenti riservati (solo i miei, segnati letti), richiesta di modifica dei dati
approvata dall'ufficio, utente senza scheda."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import Azienda
from personale.models import ContrattoLavoro, Dipendente, DocumentoDipendente, RichiestaModifica

OGGI = datetime.date.today()


@pytest.fixture
def s(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    azienda = Azienda.objects.get(pk=1)
    u = User.objects.create_user("mario", "m@x.it", "x")
    u.user_permissions.add(Permission.objects.get(codename="add_assenza"))
    mario = Dipendente.objects.create(azienda=azienda, nome="Mario", cognome="Rossi", utente=u, email="m@x.it")
    altro = Dipendente.objects.create(azienda=azienda, nome="Luca", cognome="Bianchi")
    ContrattoLavoro.objects.create(azienda=azienda, dipendente=mario, dal=OGGI.replace(month=1, day=1), ccnl="Commercio", livello="3",
                                   retribuzione_annua=Decimal(28000), mensilita=14)
    mio = DocumentoDipendente.objects.create(azienda=azienda, dipendente=mario, titolo="Cedolino ottobre", file=SimpleUploadedFile("c.pdf", b"%PDF-1"))
    suo = DocumentoDipendente.objects.create(azienda=azienda, dipendente=altro, titolo="Cedolino di Luca", file=SimpleUploadedFile("l.pdf", b"%PDF-1"))
    return {"u": u, "mario": mario, "mio": mio, "suo": suo}


def test_profilo_e_documenti(client, s):
    client.force_login(s["u"])
    html = client.get("/personale/profilo/").content.decode()
    assert "Mario Rossi" in html and "Commercio" in html and "Cedolino ottobre" in html and "Cedolino di Luca" not in html
    assert "2000,00" in html or "2.000,00" in html
    assert client.get(f"/personale/documento/{s['mio'].pk}/").status_code == 200
    s["mio"].refresh_from_db()
    assert s["mio"].letto_il is not None
    assert client.get(f"/personale/documento/{s['suo'].pk}/").status_code == 404


def test_richiesta_di_modifica(client, s):
    client.force_login(s["u"])
    client.post("/personale/profilo/", {"email": "", "telefono": "", "altro": ""})
    assert not RichiestaModifica.objects.exists()
    client.post("/personale/profilo/", {"email": "nuova@x.it", "telefono": "333", "altro": "IBAN nuovo"})
    r = RichiestaModifica.objects.get()
    client.force_login(User.objects.create_superuser("hr", "h@x.it", "x"))
    assert "Approva" in client.get(f"/personale/richieste/{r.pk}/").content.decode()
    client.post(f"/personale/richieste/{r.pk}/decidi/", {"esito": "approva"})
    s["mario"].refresh_from_db()
    r.refresh_from_db()
    assert s["mario"].email == "nuova@x.it" and s["mario"].telefono == "333" and r.stato == "approvata"


def test_senza_scheda(client, db):
    client.force_login(User.objects.create_user("ospite"))
    assert "non è collegato" in client.get("/personale/profilo/").content.decode()
