"""PLT-09: modelli di stampa per azienda e documento (colore, righe d'intestazione, testi con segnaposto, piè di
pagina, colonne nascoste), con anteprima e ritorno all'originale. Si guarda l'HTML che va a WeasyPrint."""
import pytest
from django.apps import apps

from core.models import Azienda, ModelloStampa

pytestmark = pytest.mark.skipif(not apps.is_installed("vendite"), reason="serve vendite")


@pytest.fixture
def s(db, superuser):
    from contatti.models import Contatto
    from vendite.models import OrdineVendita
    az = Azienda.objects.get(pk=1)
    superuser.profilo.aziende.set([az])
    cliente = Contatto.objects.create(azienda=az, nome="Rossi Srl", cliente=True, partita_iva="12345678903")
    ordine = OrdineVendita.objects.create(azienda=az, cliente=cliente, numero="PR/2026/0001")
    return {"az": az, "ordine": ordine, "chiave": "vendite.ordini:0"}


def _html(client, ordine):
    return client.get(f"/vendite/ordini/{ordine.pk}/stampa/0/?html=1").content.decode()


def test_senza_modello_la_stampa_originale(client, s):
    html = _html(client, s["ordine"])
    assert "Rossi Srl" in html and "col-sconto" in html and ".col-sconto { display: none; }" not in html


def test_modello_dell_azienda(client, s):
    m = ModelloStampa.objects.create(azienda=s["az"], report=s["chiave"], colore="#aa0000", righe_intestazione="Tel. 06 123 · REA RM-1",
                                     testo_iniziale="Gentile {{ cliente }}, ecco il {{ documento }}.",
                                     testo_finale="Condizioni: <b>pagamento</b> a 30 giorni. {{ inesistente }}",
                                     piede="Acme Srl · capitale 10.000 €", colonne_nascoste=["sconto", "iva"])
    html = _html(client, s["ordine"])
    assert "Tel. 06 123 · REA RM-1" in html and "Gentile Rossi Srl, ecco il" in html and "Acme Srl · capitale" in html
    assert "&lt;b&gt;pagamento&lt;/b&gt;" in html                                     # il testo dell'utente non porta markup
    assert ".col-sconto { display: none; }" in html and ".col-iva { display: none; }" in html and "#aa0000" in html
    m.attivo = False                                                                 # torna all'originale
    m.save()
    assert "Gentile Rossi" not in _html(client, s["ordine"])


def test_modello_per_tutte_e_proprio_che_vince(client, s):
    ModelloStampa.objects.create(azienda=None, report=s["chiave"], testo_iniziale="PER TUTTE")
    assert "PER TUTTE" in _html(client, s["ordine"])
    ModelloStampa.objects.create(azienda=s["az"], report=s["chiave"], testo_iniziale="SOLO NOSTRO")
    html = _html(client, s["ordine"])
    assert "SOLO NOSTRO" in html and "PER TUTTE" not in html


def test_gestione_anteprima_e_originale(client, s):
    html = client.get("/core/stampe/nuovo/").content.decode()
    assert "Preventivi e ordini · Stampa" in html or "Stampa" in html
    r = client.post("/core/stampe/nuovo/", {"report": s["chiave"], "azienda": s["az"].pk, "colore": "#123456", "mostra_logo": "on",
                                            "testo_iniziale": "Ciao {{ cliente }}", "colonne_nascoste": ["sconto", "codice"], "attivo": "on"})
    m = ModelloStampa.objects.get()
    assert r.status_code == 302 and m.colonne_nascoste == ["sconto"]                 # «codice» non è di questo documento
    anteprima = client.get(f"/stampe/{m.pk}/anteprima/?html=1").content.decode()
    assert "Ciao Rossi Srl" in anteprima
    client.post("/core/stampe/nuovo/", {"report": s["chiave"], "azienda": s["az"].pk, "colore": "#123456", "attivo": "on"})
    assert ModelloStampa.objects.count() == 1                                        # niente doppioni
    dettaglio = client.get(f"/core/stampe/{m.pk}/").content.decode()
    assert "Torna all&#x27;originale" in dettaglio or "Torna all'originale" in dettaglio


@pytest.mark.pdf
def test_pdf_vero_con_il_modello(client, s):
    from io import BytesIO

    from pypdf import PdfReader

    from core import report
    if not report.disponibile():
        pytest.skip("WeasyPrint non disponibile qui: deploy/test-pdf.sh")
    ModelloStampa.objects.create(azienda=s["az"], report=s["chiave"], testo_finale="Condizioni di vendita: 30 giorni",
                                 piede="Acme Srl · REA RM-123", colonne_nascoste=["sconto"])
    r = client.get(f"/vendite/ordini/{s['ordine'].pk}/stampa/0/")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    testo = "".join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
    assert "Condizioni di vendita: 30 giorni" in testo and "Acme Srl · REA RM-123" in testo and "Sconto" not in testo
