"""Cassa: movimenti col segno giusto, chiusura con differenza e blocco, annullamento dell'ultima, incassi in contanti
dalla fattura, rimborso di una nota spese in contanti, pagine."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from cassa import operazioni
from cassa.models import Cassa, ChiusuraCassa, MovimentoCassa
from contatti.models import Contatto
from core.models import Azienda
from fatturazione import operazioni as fatture
from fatturazione.models import Fattura, Incasso, Scadenza

OGGI = timezone.localdate()
IERI = OGGI - datetime.timedelta(days=1)


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    cassa = Cassa.objects.create(azienda=azienda, nome="Cassa sede", saldo_iniziale=Decimal("100.00"),
                                 dal=OGGI - datetime.timedelta(days=10), predefinita=True)
    return {"azienda": azienda, "cassa": cassa}


def _fattura(s, importo="50.00"):
    cliente = Contatto.objects.create(azienda=s["azienda"], nome="Bar Centrale", cliente=True)
    f = Fattura.objects.create(azienda=s["azienda"], cliente=cliente, numero="FT/9")
    Fattura.objects.filter(pk=f.pk).update(stato=Fattura.EMESSA, totale=Decimal(importo))
    Scadenza.objects.create(fattura=f, data=OGGI, importo=Decimal(importo))
    return Fattura.objects.get(pk=f.pk)


def test_movimenti_e_segno(s):
    c = s["cassa"]
    operazioni.registra(c, "30", MovimentoCassa.SPESA, data=IERI, descrizione="Francobolli")    # esce anche se positivo
    operazioni.registra(c, "200", MovimentoCassa.PRELIEVO, data=IERI)
    operazioni.registra(c, "150", MovimentoCassa.VERSAMENTO, data=OGGI)
    assert c.saldo_al(IERI) == Decimal("270.00") and c.saldo == Decimal("120.00")
    with pytest.raises(ValidationError):
        operazioni.registra(c, "0", MovimentoCassa.ALTRO)
    with pytest.raises(ValidationError):
        operazioni.registra(c, "5", MovimentoCassa.ALTRO, data=c.dal - datetime.timedelta(days=1))


def test_chiusura_con_ammanco_e_blocco(s):
    c = s["cassa"]
    operazioni.registra(c, "40", MovimentoCassa.ALTRO, data=IERI)
    ch = operazioni.chiudi(c, IERI, Decimal("138.50"), nota="monete contate due volte")
    assert (ch.apertura, ch.entrate, ch.atteso, ch.differenza) == (Decimal("100.00"), Decimal("40.00"), Decimal("140.00"), Decimal("-1.50"))
    diff = MovimentoCassa.objects.get(causale=MovimentoCassa.DIFFERENZA)
    assert diff.importo == Decimal("-1.50") and diff.chiusura == ch and c.saldo == Decimal("138.50")
    with pytest.raises(ValidationError, match="chiusa fino al"):
        operazioni.registra(c, "5", MovimentoCassa.ALTRO, data=IERI)
    with pytest.raises(ValidationError, match="già chiusa"):
        operazioni.chiudi(c, IERI, Decimal("1"))
    with pytest.raises(ValidationError, match="non è ancora finita"):
        operazioni.chiudi(c, OGGI + datetime.timedelta(days=1), Decimal("1"))
    operazioni.registra(c, "10", MovimentoCassa.ALTRO, data=OGGI)
    ch2 = operazioni.chiudi(c, OGGI, Decimal("148.50"))
    assert ch2.apertura == Decimal("138.50") and ch2.differenza == 0 and MovimentoCassa.objects.filter(causale="differenza").count() == 1
    with pytest.raises(ValidationError, match="solo l'ultima"):
        operazioni.annulla_chiusura(ch)
    pk2 = ch2.pk
    operazioni.annulla_chiusura(ch2)
    assert not MovimentoCassa.objects.filter(chiusura_id=pk2).exists() and ChiusuraCassa.objects.count() == 1
    assert MovimentoCassa.objects.filter(chiusura__isnull=True).count() == 1


def test_incasso_in_contanti_entra_in_cassa(s):
    f = _fattura(s)
    fatture.incassa_fattura(f, Decimal("50.00"), metodo="contanti")
    m = MovimentoCassa.objects.get()
    assert m.causale == MovimentoCassa.INCASSO and m.importo == Decimal("50.00") and m.incasso.scadenza.fattura == f
    assert s["cassa"].saldo == Decimal("150.00")
    fatture.annulla_incasso(Incasso.objects.get())                          # annullato prima della chiusura: sparisce
    assert not MovimentoCassa.objects.exists()
    fatture.incassa_fattura(f, Decimal("20.00"), metodo="bonifico")          # bonifico: la cassa non c'entra
    assert not MovimentoCassa.objects.exists()


def test_incasso_dopo_la_chiusura_va_al_giorno_dopo(s):
    operazioni.chiudi(s["cassa"], OGGI, Decimal("100.00"))
    f = _fattura(s)
    fatture.incassa_fattura(f, Decimal("50.00"), data=OGGI, metodo="contanti")
    m = MovimentoCassa.objects.get(causale=MovimentoCassa.INCASSO)
    assert m.data == OGGI + datetime.timedelta(days=1)
    fatture.annulla_incasso(Incasso.objects.get())
    assert not MovimentoCassa.objects.filter(causale=MovimentoCassa.INCASSO).exists()


def test_pagine(client, s):
    root = User.objects.create_superuser("root", "r@x.it", "x")
    client.force_login(root)
    c = s["cassa"]
    html = client.get(f"/cassa/casse/{c.pk}/").content.decode()
    assert "Saldo atteso" in html and "Chiudi la cassa" in html
    r = client.post("/cassa/movimenti/nuovo/", {"cassa": c.pk, "data": OGGI.isoformat(), "causale": "rimborso", "importo": "12.00",
                                               "descrizione": "Taxi"})
    assert r.status_code == 302
    m = MovimentoCassa.objects.get()
    assert m.importo == Decimal("-12.00") and m.utente == root
    assert "Nuovo movimento" in client.get(f"/cassa/casse/{c.pk}/").content.decode()
    assert client.get(f"/cassa/casse/{c.pk}/chiudi/").status_code == 200
    r = client.post(f"/cassa/casse/{c.pk}/chiudi/", {"data": OGGI.isoformat(), "contato": "90,00"})
    assert r.status_code == 302 and ChiusuraCassa.objects.get().differenza == Decimal("2.00")
    assert client.get(f"/cassa/movimenti/{m.pk}/modifica/").status_code == 403                 # chiuso: non si cambia
    assert client.post(f"/cassa/casse/{c.pk}/chiudi/", {"data": OGGI.isoformat(), "contato": "abc"}).status_code == 200
    altra = Cassa.objects.create(azienda=s["azienda"], nome="Piccola cassa", predefinita=True)
    c.refresh_from_db()
    assert altra.predefinita and not c.predefinita                                              # una sola predefinita


def test_rimborso_nota_spese_in_contanti(client, s):
    from django.apps import apps
    if not apps.is_installed("spese"):
        pytest.skip("senza note spese")
    from personale.models import Dipendente
    from spese.models import NotaSpese
    root = User.objects.create_superuser("hr", "h@x.it", "x")
    mario = Dipendente.objects.create(azienda=s["azienda"], nome="Mario", cognome="Rossi")
    nota = NotaSpese.objects.create(azienda=s["azienda"], dipendente=mario, titolo="Trasferta")
    NotaSpese.objects.filter(pk=nota.pk).update(stato=NotaSpese.APPROVATA, totale=Decimal("35.00"))
    client.force_login(root)
    assert "Pagata in contanti" in client.get(f"/spese/rimborso/{nota.pk}/").content.decode()
    r = client.post(f"/spese/rimborso/{nota.pk}/", {"cassa": s["cassa"].pk, "movimento": "", "data": ""})
    assert r.status_code == 302
    nota.refresh_from_db()
    m = MovimentoCassa.objects.get()
    assert nota.stato == NotaSpese.RIMBORSATA and m.importo == Decimal("-35.00") and m.documento == nota
    assert operazioni.movimenti_del_documento(nota).count() == 1
