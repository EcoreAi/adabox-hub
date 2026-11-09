"""Righe opzionali e modelli di preventivo: totali senza le opzioni, scelta del cliente dalla pagina online con il totale
che segue, opzioni non scelte tolte alla conferma, modello applicato a una bozza."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from vendite import operazioni
from vendite.models import ModelloPreventivo, OrdineVendita, RigaModelloPreventivo, RigaVendita


@pytest.fixture
def s(db, settings):
    settings.SITO_URL = "https://hub.esempio.it"
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi", cliente=True, email="r@x.it")
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente)
    base = RigaVendita.objects.create(ordine=o, descrizione="Sito web", quantita=1, prezzo=Decimal("1000"))
    extra = RigaVendita.objects.create(ordine=o, descrizione="Manutenzione annuale", quantita=1, prezzo=Decimal("300"), opzionale=True)
    o.ricalcola()
    return {"azienda": azienda, "o": OrdineVendita.objects.get(pk=o.pk), "base": base, "extra": extra}


def test_totali_e_conferma(s):
    o = s["o"]
    assert o.imponibile == Decimal("1000.00")                               # l'opzione non conta
    operazioni.conferma(o)
    assert list(o.righe.values_list("descrizione", flat=True)) == ["Sito web"]


def test_scelta_online(client, s):
    o = s["o"]
    OrdineVendita.objects.filter(pk=o.pk).update(stato=OrdineVendita.INVIATO)
    o.refresh_from_db()
    url = operazioni.link(o).replace("https://hub.esempio.it", "")
    html = client.get(url).content.decode()
    assert "Opzionale" in html and "Con le opzioni scelte" in html and 'name="opzione"' in html
    r = client.post(url, {"azione": "accetta", "nome": "Mario Rossi", "conferma": "1", "opzione": [s["extra"].pk]})
    assert r.status_code == 200
    o.refresh_from_db()
    assert o.risposta == "accettato" and o.imponibile == Decimal("1300.00") and o.stato == OrdineVendita.CONFERMATO
    assert o.righe.count() == 2 and o.righe.get(pk=s["extra"].pk).scelta


def test_modello(client, s):
    m = ModelloPreventivo.objects.create(azienda=s["azienda"], nome="Sito vetrina", note="Tempi: 30 giorni.", giorni_validita=15)
    RigaModelloPreventivo.objects.create(modello=m, descrizione="Hosting", quantita=1, prezzo=Decimal("120"))
    RigaModelloPreventivo.objects.create(modello=m, descrizione="SEO", quantita=1, prezzo=Decimal("400"), opzionale=True)
    nuovo = OrdineVendita.objects.create(azienda=s["azienda"], cliente=s["o"].cliente)
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    assert "Parti da un modello" in client.get(f"/vendite/ordini/{nuovo.pk}/").content.decode()
    client.post(f"/vendite/ordine/{nuovo.pk}/modello/", {"modello": m.pk})
    nuovo.refresh_from_db()
    assert nuovo.righe.count() == 2 and nuovo.righe.get(descrizione="SEO").opzionale and nuovo.imponibile == Decimal("120.00")
    assert nuovo.note == "Tempi: 30 giorni." and nuovo.validita == nuovo.data + datetime.timedelta(days=15)
