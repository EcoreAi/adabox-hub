from decimal import Decimal
from pathlib import Path

import pytest
from django.apps import apps
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

import fiscale
import prodotti
from acquisti import hooks
from acquisti.models import OrdineAcquisto, RigaAcquisto
from contatti.models import Contatto
from core.models import Azienda
from prodotti.models import Prodotto


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    fornitore = Contatto.objects.create(azienda=azienda, nome="Grossista Spa", fornitore=True, email="ordini@grossista.it")
    toner = Prodotto.objects.create(azienda=azienda, nome="Toner", costo=Decimal("38"), prezzo_vendita=Decimal("64"))
    return azienda, fornitore, toner


def test_ordine_con_costo_e_totali(scena):
    azienda, fornitore, toner = scena
    o = OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore)
    RigaAcquisto.objects.create(ordine=o, prodotto=toner, quantita=10)
    o.ricalcola()
    assert (o.imponibile, o.imposta, o.totale) == (Decimal("380.00"), Decimal("83.60"), Decimal("463.60"))


def test_numero_invio_conferma(client, superuser, scena):
    azienda, fornitore, toner = scena
    dati = {"fornitore": fornitore.pk, "data": timezone.localdate().isoformat(), "righe0-TOTAL_FORMS": "1",
            "righe0-INITIAL_FORMS": "0", "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000",
            "righe0-0-prodotto": toner.pk, "righe0-0-quantita": "5", "righe0-0-sconto": "0"}
    assert client.post("/acquisti/ordini/nuovo/", dati).status_code == 302
    o = OrdineAcquisto.objects.get()
    assert o.numero == f"OA/{timezone.localdate().year}/0001" and o.totale == Decimal("231.80")
    client.post(f"/acquisti/ordini/{o.pk}/bottone/invia/")
    assert mail.outbox[0].to == ["ordini@grossista.it"]
    client.post(f"/acquisti/ordini/{o.pk}/bottone/conferma/")
    o.refresh_from_db()
    assert o.stato == "confermato" and client.get(f"/acquisti/ordini/{o.pk}/modifica/").status_code == 403


@pytest.mark.skipif(not apps.is_installed("magazzino"), reason="serve magazzino")
def test_conferma_crea_il_ricevimento(client, superuser, scena):
    from magazzino.models import Ricevimento, giacenza
    from magazzino import operazioni
    azienda, fornitore, toner = scena
    o = OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore, numero="OA/X/1")
    RigaAcquisto.objects.create(ordine=o, prodotto=toner, quantita=12)
    client.post(f"/acquisti/ordini/{o.pk}/bottone/conferma/")
    r = Ricevimento.objects.get()
    assert r.fornitore == fornitore and r.riferimento == "OA/X/1"
    operazioni.ricevi(r)
    assert giacenza(toner) == 12
    assert f"/magazzino/ricevimenti/{r.pk}/" in client.get(f"/acquisti/ordini/{o.pk}/").content.decode()


def test_demo(scena):
    from prodotti import hooks as hp
    hp.demo(None)
    hooks.demo(None)
    hooks.demo(None)
    assert OrdineAcquisto.objects.count() == 2 and all(o.totale > 0 for o in OrdineAcquisto.objects.all())
