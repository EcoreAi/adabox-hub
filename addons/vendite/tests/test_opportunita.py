"""Preventivi dalle opportunità del CRM: «Crea preventivo», documenti collegati sulle due schede, opportunità vinta alla
conferma dell'ordine (una volta sola), nessun preventivo senza contatto o da un'opportunità persa."""
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

import crm
import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from crm.models import FaseCrm, Opportunita
from prodotti.models import Prodotto
from vendite import operazioni, opportunita
from vendite.models import OrdineVendita, RigaVendita


@pytest.fixture
def s(db):
    for app in (fiscale, prodotti, crm):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    opp = Opportunita.objects.create(azienda=azienda, titolo="Rinnovo rete uffici", contatto=cliente)
    return {"azienda": azienda, "cliente": cliente, "opp": opp,
            "monitor": Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=Decimal("200"))}


def test_preventivo_e_vittoria_alla_conferma(s):
    ordine = opportunita.crea_preventivo(s["opp"])
    assert ordine.cliente == s["cliente"] and ordine.opportunita_id == s["opp"].pk and ordine.riferimento_cliente == "Rinnovo rete uffici"
    RigaVendita.objects.create(ordine=ordine, prodotto=s["monitor"], quantita=3)
    ordine.ricalcola()
    ordine.refresh_from_db()
    operazioni.conferma(ordine)
    s["opp"].refresh_from_db()
    assert s["opp"].stato == Opportunita.VINTA and s["opp"].fase == FaseCrm.objects.filter(vinta=True).first()
    assert s["opp"].valore_atteso == ordine.imponibile
    assert list(opportunita.ordini_di(s["opp"])) == [ordine] and opportunita.di(ordine) == s["opp"]


def test_opportunita_gia_chiusa_o_senza_contatto(s):
    senza = Opportunita.objects.create(azienda=s["azienda"], titolo="Lead da fiera")
    with pytest.raises(ValidationError, match="contatto"):
        opportunita.crea_preventivo(senza)
    s["opp"].stato = Opportunita.PERSA
    s["opp"].save()
    with pytest.raises(ValidationError, match="persa"):
        opportunita.crea_preventivo(s["opp"])
    ordine = OrdineVendita.objects.create(azienda=s["azienda"], cliente=s["cliente"], opportunita_id=s["opp"].pk)
    operazioni.conferma(ordine)
    s["opp"].refresh_from_db()
    assert s["opp"].stato == Opportunita.PERSA                                        # una persa non diventa vinta


def test_pagine(client, superuser, s):
    pagina = client.get(reverse("crm:opportunita_dettaglio", args=[s["opp"].pk])).content.decode()
    assert "Preventivi e ordini" in pagina and "Crea preventivo" in pagina
    risposta = client.post(reverse("vendite:da_opportunita", args=[s["opp"].pk]))
    ordine = OrdineVendita.objects.get(opportunita_id=s["opp"].pk)
    assert risposta.url == reverse("vendite:ordini_modifica", args=[ordine.pk]) and ordine.commerciale == superuser
    assert "Nasce dall'opportunità" in client.get(reverse("vendite:ordini_dettaglio", args=[ordine.pk])).content.decode()
    assert str(ordine) in client.get(reverse("crm:opportunita_dettaglio", args=[s["opp"].pk])).content.decode()
    altra = Opportunita.objects.create(azienda=Azienda.objects.create(nome="Altra"), titolo="X", contatto=s["cliente"])
    assert client.post(reverse("vendite:da_opportunita", args=[altra.pk])).status_code == 404
