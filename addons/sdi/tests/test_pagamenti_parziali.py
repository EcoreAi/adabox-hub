"""Pagamenti ai fornitori: parziali, abbuoni, annullo, pagina; banca che paga una parte; ritenute e IVA per cassa sui
pagamenti; distinte che pagano e riaprono."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from contatti.models import Contatto
from core.models import Azienda
from sdi import passive
from sdi.models import FatturaPassiva, PagamentoPassivo, ScadenzaPassiva


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    fornitore = Contatto.objects.create(azienda=azienda, nome="Grossista", fornitore=True)
    f = FatturaPassiva.objects.create(azienda=azienda, fornitore=fornitore, numero="9", data=datetime.date(2026, 10, 1), totale=Decimal("244"),
                                      imponibile=Decimal("200"), imposta=Decimal("44"), stato=FatturaPassiva.REGISTRATA)
    sc = ScadenzaPassiva.objects.create(fattura=f, data=datetime.date(2026, 11, 1), importo=Decimal("244"))
    return {"azienda": azienda, "f": f, "s": sc}


def test_parziale_abbuono_annullo(s):
    p = passive.paga(s["s"], datetime.date(2026, 11, 2), Decimal("100"))
    s["s"].refresh_from_db()
    assert s["s"].residuo == 144 and not s["s"].pagata
    with pytest.raises(ValidationError):
        passive.paga(s["s"], importo=Decimal("200"))
    passive.paga(s["s"], datetime.date(2026, 11, 5), Decimal("140"))
    passive.paga(s["s"], datetime.date(2026, 11, 6), tipo="abbuono")          # i 4 € che il fornitore abbona
    s["s"].refresh_from_db()
    s["f"].refresh_from_db()
    assert s["s"].pagata and s["s"].pagata_il == datetime.date(2026, 11, 6) and s["f"].pagata
    passive.annulla_pagamento(p)
    s["s"].refresh_from_db()
    assert not s["s"].pagata and s["s"].residuo == 100


def test_pagina(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    url = f"/sdi/pagamenti/{s['s'].pk}/registra/"
    assert "Pagamento parziale" in client.get(f"/sdi/pagamenti/{s['s'].pk}/").content.decode()
    client.post(url, {"tipo": "pagamento", "importo": "44,00", "data": "2026-11-03", "metodo": "bonifico", "riferimento": "CRO"})
    s["s"].refresh_from_db()
    assert s["s"].pagato == 44
    p = PagamentoPassivo.objects.get()
    client.post(url, {"annulla": p.pk})
    assert not PagamentoPassivo.objects.exists()


def test_banca_paga_una_parte(s):
    from banca import abbina
    from banca.models import Conto, MovimentoBanca
    conto = Conto.objects.create(azienda=s["azienda"], nome="Principale", iban="IT60X0542811101000000123456")
    m = MovimentoBanca.objects.create(azienda=s["azienda"], conto=conto, data=datetime.date(2026, 11, 3), importo=Decimal("-100"), impronta="x")
    abbinamento, = abbina.abbina(m, [f"p{s['s'].pk}"])
    s["s"].refresh_from_db()
    assert abbinamento.importo == 100 and s["s"].residuo == 144 and abbinamento.pagamento_passivo.importo == 100
    abbina.annulla(abbinamento)
    s["s"].refresh_from_db()
    assert s["s"].pagato == 0 and not PagamentoPassivo.objects.exists()


def test_iva_per_cassa_sui_pagamenti(s):
    from iva.calcolo import _differita_pagata
    from sdi.models import RiepilogoPassiva
    RiepilogoPassiva.objects.create(fattura=s["f"], aliquota=22, imponibile=200, imposta=44, esigibilita="D")
    passive.paga(s["s"], datetime.date(2026, 11, 2), Decimal("122"))
    assert _differita_pagata(s["azienda"], 2026, [11]) == Decimal("22.00")    # metà pagata: metà dell'IVA
