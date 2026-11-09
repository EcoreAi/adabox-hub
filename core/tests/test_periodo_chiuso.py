"""Periodo chiuso e numerazioni: niente documenti nuovi, spostati o cancellati fino alla data di blocco (gli altri campi
sì), pagina dell'azienda, numerazioni modificabili che gli aggiornamenti non toccano."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from contatti.models import Contatto
from core import sequenze
from core.models import Azienda, Sequenza
from fatturazione.models import Fattura

OGGI = datetime.date.today()
PRIMA = OGGI - datetime.timedelta(days=40)


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi", cliente=True)
    vecchia = Fattura.objects.create(azienda=azienda, cliente=cliente, data=PRIMA)
    azienda.chiuso_fino_al = OGGI - datetime.timedelta(days=30)
    azienda.save()
    return {"azienda": azienda, "cliente": cliente, "vecchia": vecchia}


def test_blocco(s):
    with pytest.raises(ValidationError, match="chiuso"):
        Fattura.objects.create(azienda=s["azienda"], cliente=s["cliente"], data=PRIMA)
    Fattura.objects.create(azienda=s["azienda"], cliente=s["cliente"], data=OGGI)            # dopo la chiusura: va
    v = s["vecchia"]
    v.pagata = True
    v.save(update_fields=["pagata"])                                                          # un altro campo: va
    v.note = "nota"
    v.save()
    v.data = OGGI
    with pytest.raises(ValidationError):
        v.save()                                                                              # spostarla fuori: no
    with pytest.raises(ValidationError):
        Fattura.objects.get(pk=v.pk).delete()


def test_pagine(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    assert "Periodo chiuso" in client.get(f"/core/aziende/{s['azienda'].pk}/").content.decode()
    client.post(f"/aziende/{s['azienda'].pk}/periodo-chiuso/", {"data": ""})
    s["azienda"].refresh_from_db()
    assert s["azienda"].chiuso_fino_al is None
    client.post(f"/aziende/{s['azienda'].pk}/periodo-chiuso/", {"data": (OGGI + datetime.timedelta(days=1)).isoformat()})
    s["azienda"].refresh_from_db()
    assert s["azienda"].chiuso_fino_al is None                                                # nel futuro: no


def test_numerazioni(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get("/impostazioni/numerazioni/").content.decode()
    assert "fatturazione.fattura" in html
    seq = Sequenza.objects.get(codice="fatturazione.fattura", azienda=s["azienda"])
    client.post("/impostazioni/numerazioni/", {"sequenza": seq.pk, "formato": "FT-{anno}-{numero:05d}", "prossimo": "120", "azzera": "anno"})
    seq.refresh_from_db()
    assert seq.formato == "FT-{anno}-{numero:05d}" and seq.prossimo == 120 and seq.personalizzata
    client.post("/impostazioni/numerazioni/", {"sequenza": seq.pk, "formato": "senza numero", "prossimo": "1", "azzera": "anno"})
    seq.refresh_from_db()
    assert seq.formato == "FT-{anno}-{numero:05d}"
    sequenze.crea([{"codice": "fatturazione.fattura", "formato": "{numero}/{anno}", "azzera": "anno"}], [s["azienda"]])
    seq.refresh_from_db()
    assert seq.formato == "FT-{anno}-{numero:05d}"                                            # l'aggiornamento non la tocca
    assert sequenze.prossimo("fatturazione.fattura", s["azienda"]) == f"FT-{OGGI.year}-00120"
