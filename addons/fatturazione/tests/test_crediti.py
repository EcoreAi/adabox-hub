"""Crediti dei clienti: eccedenza di un pagamento come credito, acconto registrato a mano, uso del credito sulle
scadenze di un'altra fattura, annullo che lo restituisce, pagine."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from contatti.models import Contatto
from core.models import Azienda
from fatturazione import operazioni
from fatturazione.models import CreditoCliente, Fattura, Incasso, Scadenza


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    rossi = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    return {"azienda": azienda, "rossi": rossi}


def _fattura(s, importo, numero):
    f = Fattura.objects.create(azienda=s["azienda"], cliente=s["rossi"], numero=numero)
    Fattura.objects.filter(pk=f.pk).update(stato=Fattura.EMESSA, totale=Decimal(importo))
    Scadenza.objects.create(fattura=f, data=datetime.date(2026, 12, 31), importo=Decimal(importo))
    return Fattura.objects.get(pk=f.pk)


def test_eccedenza_e_uso(s):
    prima, seconda = _fattura(s, "100.00", "1"), _fattura(s, "80.00", "2")
    with pytest.raises(ValidationError):
        operazioni.incassa_fattura(prima, Decimal("150"))
    operazioni.incassa_fattura(prima, Decimal("150"), eccedenza_a_credito=True)
    prima.refresh_from_db()
    credito = CreditoCliente.objects.get()
    assert prima.pagata and credito.importo == 50 and credito.origine == "eccedenza" and credito.residuo == 50
    incassi = operazioni.usa_credito(seconda)
    seconda.refresh_from_db()
    assert sum(i.importo for i in incassi) == 50 and seconda.residuo == 30 and incassi[0].tipo == Incasso.CREDITO
    assert CreditoCliente.objects.get().residuo == 0
    with pytest.raises(ValidationError, match="non ha crediti"):
        operazioni.usa_credito(seconda)
    operazioni.annulla_incasso(incassi[0])
    assert CreditoCliente.objects.get().residuo == 50                    # annullato: il credito torna


def test_acconto_e_pagine(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    r = client.post("/fatturazione/crediti/nuovo/", {"cliente": s["rossi"].pk, "data": "2026-11-09", "importo": "200", "origine": "acconto",
                                                    "metodo": "bonifico", "riferimento": "CRO1", "note": ""})
    assert r.status_code == 302 and CreditoCliente.objects.get().utente.username == "root"
    f = _fattura(s, "120.00", "3")
    html = client.get(f"/fatturazione/fatture/{f.pk}/").content.decode()
    assert "Usa il credito su questa fattura" in html and "200,00" in html
    client.post(f"/fatturazione/fatture/{f.pk}/usa-credito/")
    f.refresh_from_db()
    assert f.pagata and CreditoCliente.objects.get().residuo == 80
    assert "Da usare" in client.get("/fatturazione/crediti/").content.decode()
    c = CreditoCliente.objects.get()
    assert client.get(f"/fatturazione/crediti/{c.pk}/modifica/").status_code == 403        # già usato: non si cambia
    client.post(f"/fatturazione/fatture/{_fattura(s, '10.00', '4').pk}/incasso/", {"importo": "25", "data": "2026-11-09", "tipo": "incasso",
                                                                                   "metodo": "bonifico", "eccedenza": "1"})
    assert CreditoCliente.objects.filter(origine="eccedenza").get().importo == 15
