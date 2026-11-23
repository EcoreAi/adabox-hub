"""Misure aziendali delle Vendite: ordinato e preventivi aperti."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from contatti.models import Contatto
from core import misure
from core.models import Azienda
from core.viste.interroga import richiesta_di
from vendite.models import OrdineVendita


@pytest.fixture
def req(db):
    return richiesta_di(User.objects.create_superuser("capo", "capo@example.com", "x"))


def _ordine(stato, imponibile):
    azienda = Azienda.objects.get(pk=1)
    cliente, _ = Contatto.objects.get_or_create(azienda=azienda, nome="Rossi Srl", defaults={"cliente": True})
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente)
    OrdineVendita.objects.filter(pk=o.pk).update(stato=stato, imponibile=Decimal(imponibile))
    return o


def test_ordinato_solo_confermati(req):
    _ordine("confermato", "1000")
    _ordine("bozza", "400")
    assert misure.calcola("vendite.ordinato", req, periodo="anno")["valore"] == 1000


def test_preventivi_aperti(req):
    for stato, imponibile in (("bozza", "100"), ("bozza", "200"), ("inviato", "300"), ("confermato", "999")):
        _ordine(stato, imponibile)
    assert misure.calcola("vendite.preventivi_aperti", req)["valore"] == 3
    assert misure.calcola("vendite.valore_preventivi_aperti", req)["valore"] == 600


def test_ordinato_per_commerciale_e_filtrabile(req):
    """«Filtra» sul grafico dell'ordinato offre cliente e commerciale; il link porta il commerciale."""
    anna = User.objects.create_user("anna", "a@example.com", "x")
    o = _ordine("confermato", "1000")
    OrdineVendita.objects.filter(pk=o.pk).update(commerciale=anna)
    _ordine("confermato", "300")
    spec = {"misura_aziendale": "vendite.ordinato", "per": "mese", "periodo": "anno"}
    assert [f["campo"] for f in misure.filtri_grafico(spec, req)] == ["cliente", "commerciale"]
    r = misure.calcola("vendite.ordinato", req, periodo="anno", per="commerciale", scelti={"commerciale": anna.pk})
    assert r["valore"] == 1000 and f"f_commerciale={anna.pk}" in r["url"]
