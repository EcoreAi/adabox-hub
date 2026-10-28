import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from fatturazione import hooks, operazioni
from fatturazione.models import DatiFiscali, Fattura, RigaFattura, Scadenza
from fiscale.models import AliquotaIva, TerminePagamento
from prodotti.models import Prodotto
from vendite.models import OrdineVendita, RigaVendita

ANNO = timezone.localdate().year
OGGI = timezone.localdate()


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", email="amministrazione@rossi.it",
                                      cliente=True, partita_iva="01234567897")
    monitor = Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=Decimal("200"))
    corso = Prodotto.objects.create(azienda=azienda, nome="Corso", tipo="servizio", prezzo_vendita=Decimal("100"),
                                    aliquota_iva=AliquotaIva.objects.get(codice="N4"))
    return azienda, cliente, monitor, corso


def _fattura(azienda, cliente, righe, **extra):
    f = Fattura.objects.create(azienda=azienda, cliente=cliente, **extra)
    for prodotto, quantita in righe:
        RigaFattura.objects.create(fattura=f, prodotto=prodotto, quantita=Decimal(quantita))
    f.ricalcola()
    return f


def _form(cliente, righe, **extra):
    dati = {"cliente": cliente.pk, "tipo": "TD01", "data": OGGI.isoformat(), "righe0-TOTAL_FORMS": str(len(righe)),
            "righe0-INITIAL_FORMS": "0", "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000", **extra}
    for i, r in enumerate(righe):
        dati.update({f"righe0-{i}-{k}": v for k, v in {"quantita": "1", "sconto": "0", **r}.items()})
    return dati


def test_bozza_dal_form_senza_numero(client, superuser, scena):
    azienda, cliente, monitor, corso = scena
    r = client.post("/fatturazione/fatture/nuovo/", _form(cliente, [{"prodotto": monitor.pk, "quantita": "2"},
                                                                     {"prodotto": corso.pk}]))
    f = Fattura.objects.get()
    assert r.status_code == 302 and f.numero == "" and f.stato == "bozza" and f.azienda == azienda
    assert (f.imponibile, f.imposta, f.totale) == (Decimal("500.00"), Decimal("88.00"), Decimal("588.00"))
    html = client.get(f"/fatturazione/fatture/{f.pk}/").content.decode()
    assert "588,00 €" in html and "bottone/emetti/" in html and "bottone/nota_di_credito/" not in html


def test_emissione_numero_e_scadenze(client, superuser, scena):
    azienda, cliente, monitor, _ = scena
    termine = TerminePagamento.objects.get(nome__icontains="30-60")
    a = _fattura(azienda, cliente, [(monitor, 1)], termine_pagamento=termine)
    b = _fattura(azienda, cliente, [(monitor, 2)])
    client.post(f"/fatturazione/fatture/{a.pk}/bottone/emetti/")
    client.post(f"/fatturazione/fatture/{b.pk}/bottone/emetti/")
    a.refresh_from_db(), b.refresh_from_db()
    assert (a.numero, b.numero, a.stato) == (f"1/{ANNO}", f"2/{ANNO}", "emessa") and a.emessa_il
    assert [s.importo for s in a.scadenze.all()] == [Decimal("122.00"), Decimal("122.00")]
    assert all(s.modalita == "MP12" for s in a.scadenze.all())
    assert [(s.data, s.importo) for s in b.scadenze.all()] == [(b.data, Decimal("488.00"))]   # senza termine: subito
    assert str(a) == f"Fattura 1/{ANNO}"
    r = client.post(f"/fatturazione/fatture/{a.pk}/modifica/", _form(cliente, []))
    assert r.status_code == 403                                      # emessa: non si modifica più


def test_controlli_prima_dell_emissione(client, superuser, scena):
    azienda, cliente, monitor, _ = scena
    vuota = Fattura.objects.create(azienda=azienda, cliente=cliente)
    with pytest.raises(ValidationError, match="non ha righe"):
        operazioni.emetti(vuota)
    privato = Contatto.objects.create(azienda=azienda, nome="Mario Bianchi", cliente=True)
    f = _fattura(azienda, privato, [(monitor, 1)])
    r = client.post(f"/fatturazione/fatture/{f.pk}/bottone/emetti/", follow=True)
    assert "né partita IVA né codice fiscale" in r.content.decode()
    f.refresh_from_db()
    assert f.stato == "bozza" and f.numero == ""
    successiva = _fattura(azienda, cliente, [(monitor, 1)], data=OGGI)
    operazioni.emetti(successiva)
    prima = _fattura(azienda, cliente, [(monitor, 1)], data=OGGI - datetime.timedelta(days=1))
    if prima.data.year == OGGI.year:
        with pytest.raises(ValidationError, match="ordine delle date"):
            operazioni.emetti(prima)


def test_incassi(client, superuser, scena):
    azienda, cliente, monitor, _ = scena
    f = _fattura(azienda, cliente, [(monitor, 1)], termine_pagamento=TerminePagamento.objects.get(nome__icontains="30-60"))
    operazioni.emetti(f)
    prima, seconda = f.scadenze.all()
    client.post(f"/fatturazione/scadenze/{prima.pk}/bottone/incassa/")
    f.refresh_from_db()
    assert not f.pagata and Scadenza.objects.get(pk=prima.pk).pagata_il == OGGI
    client.post("/fatturazione/scadenze/azione/incassa_selezionate/", {"pk": [seconda.pk]})
    f.refresh_from_db()
    assert f.pagata
    assert client.get("/fatturazione/scadenze/nuovo/").status_code == 403


def test_nota_di_credito_stessa_sequenza(client, superuser, scena):
    azienda, cliente, monitor, _ = scena
    f = _fattura(azienda, cliente, [(monitor, 3)])
    operazioni.emetti(f)
    r = client.post(f"/fatturazione/fatture/{f.pk}/bottone/nota_di_credito/")
    nota = Fattura.objects.get(tipo="TD04")
    assert r.status_code == 302 and r["Location"].endswith(f"/fatturazione/fatture/{nota.pk}/")
    assert nota.fattura_origine == f and nota.totale == f.totale and nota.stato == "bozza"
    operazioni.emetti(nota)
    assert nota.numero == f"2/{ANNO}" and nota.pagata and not nota.scadenze.exists()
    assert str(nota) == f"Nota di credito 2/{ANNO}"
    with pytest.raises(ValidationError):
        operazioni.nota_di_credito(nota)                              # una nota non si storna
    assert f"Stornata da" in client.get(f"/fatturazione/fatture/{f.pk}/").content.decode()


def test_annulla_solo_bozza(client, superuser, scena):
    azienda, cliente, monitor, _ = scena
    f = _fattura(azienda, cliente, [(monitor, 1)])
    client.post(f"/fatturazione/fatture/{f.pk}/bottone/annulla/")
    f.refresh_from_db()
    assert f.stato == "annullata"
    with pytest.raises(ValidationError):
        operazioni.emetti(f)


def test_fattura_da_ordine_confermato(client, superuser, scena):
    azienda, cliente, monitor, corso = scena
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente, numero="PV/1")
    RigaVendita.objects.create(ordine=o, prodotto=monitor, quantita=2, sconto=10)
    RigaVendita.objects.create(ordine=o, prodotto=corso)
    o.ricalcola()
    r = client.post(f"/fatturazione/da-ordine/{o.pk}/", follow=True)
    assert not Fattura.objects.exists() and "solo un ordine confermato" in r.content.decode()
    client.post(f"/vendite/ordini/{o.pk}/bottone/conferma/")
    o.refresh_from_db()
    assert "Crea la fattura" in client.get(f"/vendite/ordini/{o.pk}/").content.decode()
    client.post(f"/fatturazione/da-ordine/{o.pk}/")
    f = Fattura.objects.get()
    assert f.ordine == o and f.totale == o.totale and f.righe.count() == 2 and o.numero_ordine in f.causale
    assert f"/fatturazione/fatture/{f.pk}/" in client.get(f"/vendite/ordini/{o.pk}/").content.decode()


def test_invio_email(client, superuser, scena):
    azienda, cliente, monitor, _ = scena
    f = _fattura(azienda, cliente, [(monitor, 1)])
    operazioni.emetti(f)
    client.post(f"/fatturazione/fatture/{f.pk}/bottone/invia/")
    assert mail.outbox[-1].to == ["amministrazione@rossi.it"] and f"1/{ANNO}" in mail.outbox[-1].subject


def test_dati_fiscali_su_azienda(client, superuser, scena):
    azienda = scena[0]
    assert "Inserisci" in client.get(f"/core/aziende/{azienda.pk}/").content.decode()
    DatiFiscali.objects.create(azienda=azienda, iban="IT60X0542811101000000123456")
    assert "IT60X0542811101000000123456" in client.get(f"/core/aziende/{azienda.pk}/").content.decode()


def test_dashboard(client, superuser, scena):
    from fatturazione.dashboard import kpi
    azienda, cliente, monitor, _ = scena
    operazioni.emetti(_fattura(azienda, cliente, [(monitor, 1)]))
    nota = operazioni.nota_di_credito(Fattura.objects.get())
    nota.righe.update(quantita=Decimal("0.5"))
    for r in nota.righe.all():
        r.save()
    nota.ricalcola()
    operazioni.emetti(nota)
    richiesta = type("R", (), {"user": superuser, "azienda": azienda})()
    dati = kpi(richiesta)
    assert dati["kpi"][0]["valore"].startswith("100") and dati["kpi"][1]["valore"].startswith("244")


def test_demo(scena):
    from prodotti import hooks as hp
    from vendite import hooks as hv
    hp.demo(None)
    hv.demo(None)
    hooks.demo(None)
    hooks.demo(None)
    fatture = Fattura.objects.all()
    assert fatture.count() == 2 and fatture.filter(stato="emessa").count() == 1
    assert DatiFiscali.objects.filter(azienda_id=1).exists()
    assert Fattura.objects.filter(pagata=True).exists()


@pytest.mark.pdf
def test_stampa_pdf_e_invio_con_allegato(client, superuser, scena):
    from core import report
    if not report.disponibile():
        pytest.skip("WeasyPrint senza Pango: deploy/test-pdf.sh")
    azienda, cliente, monitor, corso = scena
    f = _fattura(azienda, cliente, [(monitor, 1), (corso, 2)])
    operazioni.emetti(f)
    r = client.get(f"/fatturazione/fatture/{f.pk}/stampa/0/")
    assert r["Content-Type"] == "application/pdf" and r.content.startswith(b"%PDF")
    client.post(f"/fatturazione/fatture/{f.pk}/bottone/invia/")
    nome, contenuto, tipo = mail.outbox[-1].attachments[0]
    assert nome == f"Fattura 1-{ANNO}.pdf" and contenuto.startswith(b"%PDF")
