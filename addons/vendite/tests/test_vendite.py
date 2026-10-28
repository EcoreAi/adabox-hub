from decimal import Decimal
from pathlib import Path

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from prodotti.models import Listino, PrezzoListino, Prodotto
from vendite import hooks
from vendite.models import OrdineVendita, RigaVendita
from vendite.segnali import ordine_confermato

ANNO = timezone.localdate().year


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", email="ordini@rossi.it", cliente=True)
    monitor = Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=Decimal("200"))
    corso = Prodotto.objects.create(azienda=azienda, nome="Corso", tipo="servizio", prezzo_vendita=Decimal("100"),
                                    aliquota_iva=fiscale.models.AliquotaIva.objects.get(codice="N4"))
    return azienda, cliente, monitor, corso


def _form(cliente, righe, **extra):
    dati = {"cliente": cliente.pk, "data": timezone.localdate().isoformat(), "righe0-TOTAL_FORMS": str(len(righe)),
            "righe0-INITIAL_FORMS": "0", "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000", **extra}
    for i, r in enumerate(righe):
        dati.update({f"righe0-{i}-{k}": v for k, v in {"quantita": "1", "sconto": "0", **r}.items()})
    return dati


def test_preventivo_con_righe_e_totali(client, superuser, scena):
    azienda, cliente, monitor, corso = scena
    r = client.post("/vendite/ordini/nuovo/", _form(cliente, [
        {"prodotto": monitor.pk, "quantita": "2", "sconto": "10"},            # 400 - 10% = 360, IVA 22%
        {"prodotto": corso.pk},                                               # 100 esente
        {"descrizione": "Trasporto", "prezzo": "15"}]))                       # riga libera, IVA 22%
    o = OrdineVendita.objects.get()
    assert r.status_code == 302 and o.numero == f"PV/{ANNO}/0001" and o.stato == "bozza" and o.commerciale == superuser
    righe = list(o.righe.all())
    assert [(x.descrizione, x.prezzo, x.importo) for x in righe] == [
        ("Monitor", Decimal("200.0000"), Decimal("360.00")), ("Corso", Decimal("100.0000"), Decimal("100.00")),
        ("Trasporto", Decimal("15.0000"), Decimal("15.00"))]
    assert (o.imponibile, o.imposta, o.totale) == (Decimal("475.00"), Decimal("82.50"), Decimal("557.50"))
    html = client.get(f"/vendite/ordini/{o.pk}/").content.decode()
    assert "557,50 €" in html and f"/vendite/ordini/{o.pk}/bottone/conferma/" in html


def test_prezzo_da_listino(scena):
    azienda, cliente, monitor, _ = scena
    listino = Listino.objects.create(azienda=azienda, nome="Rivenditori")
    PrezzoListino.objects.create(listino=listino, prodotto=monitor, prezzo=Decimal("150"))
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente, listino=listino)
    assert RigaVendita.objects.create(ordine=o, prodotto=monitor).prezzo == Decimal("150")


def test_riga_senza_prodotto_ne_descrizione(client, superuser, scena):
    _, cliente, _, _ = scena
    r = client.post("/vendite/ordini/nuovo/", _form(cliente, [{"prezzo": "10", "quantita": "2"}]))
    assert r.status_code == 200 and not OrdineVendita.objects.exists()


def test_conferma_numero_segnale_e_blocco(client, superuser, scena):
    azienda, cliente, monitor, _ = scena
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente)
    RigaVendita.objects.create(ordine=o, prodotto=monitor)
    o.ricalcola()
    ricevuti = []
    gestore = lambda sender, ordine, utente, **kw: ricevuti.append((ordine.pk, utente))   # noqa: E731
    ordine_confermato.connect(gestore)
    try:
        client.post(f"/vendite/ordini/{o.pk}/bottone/conferma/")
        client.post(f"/vendite/ordini/{o.pk}/bottone/conferma/")          # seconda volta: niente
    finally:
        ordine_confermato.disconnect(gestore)
    o.refresh_from_db()
    assert o.stato == "confermato" and o.numero_ordine == f"OV/{ANNO}/0001" and ricevuti == [(o.pk, superuser)]
    assert client.get(f"/vendite/ordini/{o.pk}/modifica/").status_code == 403
    client.post(f"/vendite/ordini/{o.pk}/bottone/riporta_in_bozza/")
    o.refresh_from_db()
    assert o.stato == "confermato"


def test_conferma_senza_righe(client, superuser, scena):
    azienda, cliente, _, _ = scena
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente)
    client.post(f"/vendite/ordini/{o.pk}/bottone/conferma/")
    o.refresh_from_db()
    assert o.stato == "bozza"


def test_invia_per_email(client, superuser, scena):
    azienda, cliente, monitor, _ = scena
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente, numero="PV/X/1")
    RigaVendita.objects.create(ordine=o, prodotto=monitor)
    client.post(f"/vendite/ordini/{o.pk}/bottone/invia/")
    o.refresh_from_db()
    (email,) = mail.outbox
    assert o.stato == "inviato" and email.to == ["ordini@rossi.it"] and "PV/X/1" in email.subject
    from core import chatter
    assert "inviato a ordini@rossi.it" in chatter.messaggi_di(o).filter(tipo="nota").first().corpo


def test_stampa_html(client, superuser, scena):
    azienda, cliente, monitor, _ = scena
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente, numero="PV/X/9")
    RigaVendita.objects.create(ordine=o, prodotto=monitor, quantita=3)
    o.ricalcola()
    html = client.get(f"/vendite/ordini/{o.pk}/stampa/0/", {"html": 1}).content.decode()
    assert "Preventivo PV/X/9" in html and "Rossi Srl" in html and "732,00" in html


def test_demo_e_dashboard(client, superuser, scena):
    from prodotti import hooks as hooks_prodotti
    hooks_prodotti.demo(None)
    hooks.demo(None)
    hooks.demo(None)                                                     # idempotente
    assert OrdineVendita.objects.count() == 4 and OrdineVendita.objects.filter(stato="confermato").count() == 2
    assert all(o.totale > 0 for o in OrdineVendita.objects.all())
    schede = {s["slug"]: s for s in client.get("/dashboard/").context["schede"]}
    assert schede["vendite"]["kpi"][1]["valore"] == 2
