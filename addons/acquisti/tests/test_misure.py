"""Misura aziendale degli Acquisti: acquistato."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from acquisti.models import OrdineAcquisto
from contatti.models import Contatto
from core import misure
from core.models import Azienda
from core.viste.interroga import richiesta_di


@pytest.fixture
def req(db):
    return richiesta_di(User.objects.create_superuser("capo", "capo@example.com", "x"))


def test_acquistato_solo_confermati(req):
    azienda = Azienda.objects.get(pk=1)
    fornitore = Contatto.objects.create(azienda=azienda, nome="Grossista Spa", fornitore=True)
    for stato, imponibile in (("confermato", "800"), ("confermato", "200"), ("bozza", "500")):
        o = OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore)
        OrdineAcquisto.objects.filter(pk=o.pk).update(stato=stato, imponibile=Decimal(imponibile))
    r = misure.calcola("acquisti.acquistato", req, periodo="anno", per="fornitore")
    assert r["valore"] == 1000
    assert [(g["gruppo"], g["valore"]) for g in r["gruppi"]] == [("Grossista Spa", 1000)]
