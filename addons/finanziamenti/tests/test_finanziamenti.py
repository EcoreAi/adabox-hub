"""Piano delle rate (francese, italiano, preammortamento), rigenerazione che tiene le pagate, pagamento con chiusura,
annullamento, estinzione anticipata, abbinamento alla banca, pagine e riepilogo."""
import datetime
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth.models import User

from core.models import Azienda
from finanziamenti import piano
from finanziamenti.models import Finanziamento, RataFinanziamento


def _f(**k):
    dati = dict(azienda=Azienda.objects.get(pk=1), nome="Mutuo", capitale=Decimal("10000"), tasso=Decimal("6"), durata=12,
                periodicita=1, erogato_il=datetime.date(2026, 1, 15), prima_rata=datetime.date(2026, 2, 15))
    dati.update(k)
    f = Finanziamento.objects.create(**dati)
    piano.genera(f)
    return f


@pytest.mark.django_db
def test_francese_rata_costante():
    f = _f()
    rate = list(f.rate.order_by("numero"))
    assert len(rate) == 12 and rate[0].data == datetime.date(2026, 2, 15) and rate[-1].data == datetime.date(2027, 1, 15)
    assert rate[0].quota_interessi == Decimal("50.00")                       # 10.000 × 0,5%
    importi = {r.importo for r in rate[:-1]}
    assert importi == {Decimal("860.66")}                                     # rata costante
    assert sum(r.quota_capitale for r in rate) == Decimal("10000") and rate[-1].debito_residuo == 0


@pytest.mark.django_db
def test_italiano_e_preammortamento_e_tasso_zero():
    f = _f(ammortamento=Finanziamento.ITALIANO, durata=12, periodicita=3, preammortamento=1, spese_rata=Decimal("2"))
    rate = list(f.rate.order_by("numero"))
    assert len(rate) == 4 and rate[1].data == datetime.date(2026, 5, 15)
    assert rate[0].quota_capitale == 0 and rate[0].quota_interessi == Decimal("150.00") and rate[0].importo == Decimal("152.00")
    assert [r.quota_capitale for r in rate[1:]] == [Decimal("3333.33"), Decimal("3333.34"), Decimal("3333.33")]
    zero = _f(tasso=0, durata=3)
    assert [r.importo for r in zero.rate.order_by("numero")] == [Decimal("3333.33"), Decimal("3333.33"), Decimal("3333.34")]


@pytest.mark.django_db
def test_pagamento_rigenerazione_ed_estinzione():
    f = _f()
    prima, seconda = f.rate.order_by("numero")[:2]
    piano.paga(prima, datetime.date(2026, 2, 15))
    assert f.debito_residuo() == Decimal("10000") - prima.quota_capitale
    f.tasso = Decimal("3")
    f.save()
    assert piano.genera(f) == 11                                       # la pagata resta, le altre si ricalcolano
    assert f.rate.get(numero=1).pagata and f.rate.get(numero=2).quota_interessi < seconda.quota_interessi
    rata = piano.estingui(f, datetime.date(2026, 3, 17), Decimal("100"))
    assert f.rate.count() == 2 and rata.numero == 2 and rata.quota_capitale == f.debito_residuo()
    assert rata.quota_interessi > 0 and rata.spese == Decimal("100.00")
    piano.paga(rata, datetime.date(2026, 3, 17))
    f.refresh_from_db()
    assert f.stato == Finanziamento.ESTINTO and f.debito_residuo() == 0
    piano.annulla_pagamento(rata)
    f.refresh_from_db()
    assert f.stato == Finanziamento.ATTIVO
    with pytest.raises(Exception):
        piano.paga(f.rate.get(numero=1), datetime.date(2026, 4, 1))       # già pagata


@pytest.mark.django_db
def test_pagina_paga_con_la_banca_e_dettaglio(client):
    if not apps.is_installed("banca"):
        pytest.skip("Banca non installata")
    from banca.models import Conto, MovimentoBanca
    f = _f()
    rata = f.rate.get(numero=1)
    conto = Conto.objects.create(azienda=f.azienda, nome="Principale", iban="IT60X0542811101000000123456")
    m = MovimentoBanca.objects.create(azienda=f.azienda, conto=conto, data=datetime.date(2026, 2, 16), importo=-rata.importo,
                                      descrizione="Rata mutuo", impronta="x1")
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    r = client.get(f"/finanziamenti/rate/{rata.pk}/paga/")
    assert r.status_code == 200 and "Rata mutuo" in r.content.decode()
    r = client.post(f"/finanziamenti/rate/{rata.pk}/paga/", {"movimento": m.pk, "data": ""})
    rata.refresh_from_db()
    m.refresh_from_db()
    assert rata.pagata and rata.pagata_il == m.data and m.stato == MovimentoBanca.ABBINATO
    piano.annulla_pagamento(rata)
    m.refresh_from_db()
    assert m.stato != MovimentoBanca.ABBINATO
    for url in [f"/finanziamenti/finanziamenti/{f.pk}/", "/finanziamenti/rate/", "/finanziamenti/rate/calendario/",
                f"/finanziamenti/finanziamenti/{f.pk}/estingui/"]:
        assert client.get(url).status_code == 200, url


@pytest.mark.django_db
def test_nuovo_dal_form_genera_il_piano(client):
    from contatti.models import Contatto
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    banca = Contatto.objects.create(azienda=Azienda.objects.get(pk=1), nome="Banca", fornitore=True)
    r = client.post("/finanziamenti/finanziamenti/nuovo/", {
        "nome": "Chirografario", "tipo": "finanziamento", "ente": banca.pk, "capitale": "50000", "tasso": "4.5", "durata": "60",
        "periodicita": "3", "ammortamento": "francese", "erogato_il": "2026-11-01", "prima_rata": "2027-02-01",
        "preammortamento": "0", "spese_rata": "0"})
    assert r.status_code == 302, (r.context.get("form").errors if r.context and r.context.get("form") is not None else r.content.decode()[-3000:])
    f = Finanziamento.objects.get(nome="Chirografario")
    assert f.rate.count() == 20 and RataFinanziamento.objects.filter(azienda=f.azienda).count() == 20
