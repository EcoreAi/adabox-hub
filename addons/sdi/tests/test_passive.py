import io
import subprocess
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from fatturazione import fatturapa, operazioni
from fatturazione.models import DatiFiscali, Fattura, RigaFattura
from fiscale.models import AliquotaIva, TerminePagamento
from prodotti.models import Prodotto
from sdi import passive, ricezione
from sdi.models import FatturaPassiva, NotificaSdi

NOI = "01234567897"
FORNITORE = "12345678903"


@pytest.fixture
def xml_fornitore(db, settings, tmp_path):
    """Una fattura vera (passa la validazione XSD) emessa da un'altra azienda verso di noi."""
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    noi = Azienda.objects.get(pk=1)
    noi.partita_iva = NOI
    noi.save()
    fornitore = Azienda.objects.create(nome="Grossista Spa", partita_iva=FORNITORE, indirizzo="Via Po 1", cap="10100",
                                       citta="Torino", provincia="TO")
    DatiFiscali.objects.create(azienda=fornitore, iban="IT60X0542811101000000123456")
    cliente = Contatto.objects.create(azienda=fornitore, nome="Noi Srl", partita_iva=NOI, indirizzo="Via Roma 1",
                                      cap="00100", citta="Roma")
    toner = Prodotto.objects.create(azienda=fornitore, nome="Toner", prezzo_vendita=Decimal("80"))
    libro = Prodotto.objects.create(azienda=fornitore, nome="Manuale", prezzo_vendita=Decimal("30"),
                                    aliquota_iva=AliquotaIva.objects.get(codice="4"))
    f = Fattura.objects.create(azienda=fornitore, cliente=cliente,
                               termine_pagamento=TerminePagamento.objects.get(nome__icontains="30-60"))
    RigaFattura.objects.create(fattura=f, prodotto=toner, quantita=3)
    RigaFattura.objects.create(fattura=f, prodotto=libro)
    f.ricalcola()
    operazioni.emetti(f)
    nome, xml = fatturapa.genera(f)
    return noi, nome, xml, f


def test_ricezione_di_una_fattura(xml_fornitore):
    noi, nome, xml, originale = xml_fornitore
    esito, fattura = ricezione.ricevi(nome, xml)
    assert esito == "passiva" and fattura.azienda == noi
    assert fattura.fornitore.partita_iva == FORNITORE and fattura.fornitore.fornitore
    assert fattura.fornitore.azienda == noi and fattura.fornitore.citta == "Torino"
    assert (fattura.numero, fattura.data) == (originale.numero, originale.data)
    assert (fattura.imponibile, fattura.imposta, fattura.totale) == (originale.imponibile, originale.imposta,
                                                                     originale.totale)
    assert [r.descrizione for r in fattura.righe.all()] == ["Toner", "Manuale"]
    assert {(r.aliquota, r.imposta) for r in fattura.riepilogo.all()} == {(Decimal("22.00"), Decimal("52.80")),
                                                                         (Decimal("4.00"), Decimal("1.20"))}
    scadenze = list(fattura.scadenze.all())
    assert len(scadenze) == 2 and sum(s.importo for s in scadenze) == fattura.totale
    assert scadenze[0].iban == "IT60X0542811101000000123456" and scadenze[0].modalita == "MP12"
    assert ricezione.ricevi(nome, xml)[0] == "doppione" and FatturaPassiva.objects.count() == 1


def test_fornitore_esistente_riusato(xml_fornitore):
    noi, nome, xml, _ = xml_fornitore
    gia = Contatto.objects.create(azienda=noi, nome="Grossista (già in rubrica)", partita_iva=FORNITORE)
    _, fattura = ricezione.ricevi(nome, xml)
    gia.refresh_from_db()
    assert fattura.fornitore == gia and gia.fornitore


def test_fattura_non_nostra(xml_fornitore):
    _, nome, xml, _ = xml_fornitore
    altro = xml.replace(f"<IdCodice>{NOI}</IdCodice>".encode(), b"<IdCodice>99999999999</IdCodice>")
    assert ricezione.ricevi(nome, altro)[0] == "ignorato"


def test_p7m(xml_fornitore, tmp_path):
    _, nome, xml, _ = xml_fornitore
    chiave, cert, dati, firmato = (tmp_path / n for n in ("k.pem", "c.pem", "f.xml", "f.xml.p7m"))
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", chiave, "-out", cert,
                    "-subj", "/CN=Prova", "-days", "1"], check=True, capture_output=True)
    dati.write_bytes(xml)
    subprocess.run(["openssl", "cms", "-sign", "-binary", "-nodetach", "-outform", "DER", "-in", dati, "-signer", cert,
                    "-inkey", chiave, "-out", firmato], check=True, capture_output=True)
    esito, fattura = ricezione.ricevi(f"{nome}.p7m", firmato.read_bytes())
    assert esito == "passiva" and fattura.totale > 0 and fattura.nome_file.endswith(".p7m")
    import base64
    FatturaPassiva.objects.all().delete()
    assert ricezione.ricevi(f"{nome}.p7m", base64.b64encode(firmato.read_bytes()))[0] == "passiva"
    with pytest.raises(passive.FatturaNonValida):
        passive.estrai_p7m(b"spazzatura")


def test_metadati_portano_l_identificativo(xml_fornitore):
    _, nome, xml, _ = xml_fornitore
    mt = (f'<?xml version="1.0"?><ns:FileMetadati xmlns:ns="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/'
          f'messaggi/v1.0"><IdentificativoSdI>4455</IdentificativoSdI><NomeFile>{nome}</NomeFile>'
          f'</ns:FileMetadati>').encode()
    _, fattura = ricezione.ricevi(nome, xml)
    ricezione.ricevi(nome.replace(".xml", "_MT_001.xml"), mt)
    fattura.refresh_from_db()
    assert fattura.identificativo_sdi == "4455" and NotificaSdi.objects.get().tipo == "MT"


def test_caricamento_registrazione_pagamento_registro(client, superuser, xml_fornitore):
    noi, nome, xml, _ = xml_fornitore
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(nome, xml)
    r = client.post("/sdi/carica/", {"file": SimpleUploadedFile("lotto.zip", buffer.getvalue())})
    fattura = FatturaPassiva.objects.get()
    assert "Fattura ricevuta" in r.content.decode() and f"/sdi/passive/{fattura.pk}/" in r.content.decode()
    html = client.get(f"/sdi/passive/{fattura.pk}/").content.decode()
    assert "Toner" in html and "bottone/registra/" in html
    assert client.get(f"/sdi/ricevute/{fattura.pk}/originale/").content == xml
    client.post(f"/sdi/passive/{fattura.pk}/bottone/registra/")
    fattura.refresh_from_db()
    assert fattura.stato == "registrata" and fattura.registrata_il == timezone.localdate()
    oggi = timezone.localdate()
    html = client.get(f"/sdi/registro-acquisti/?anno={oggi.year}&mese={oggi.month}").content.decode()
    assert "Grossista Spa" in html and "240,00" in html
    csv = client.get(f"/sdi/registro-acquisti/?anno={oggi.year}&mese=&formato=csv").content.decode()
    assert csv.count("\n") == 3
    prima, seconda = fattura.scadenze.all()
    client.post(f"/sdi/pagamenti/{prima.pk}/bottone/paga/")
    fattura.refresh_from_db()
    assert not fattura.pagata
    client.post("/sdi/pagamenti/azione/paga_selezionate/", {"pk": [seconda.pk]})
    fattura.refresh_from_db()
    assert fattura.pagata


def test_dashboard(rf, superuser, xml_fornitore):
    from sdi.dashboard import kpi
    noi, nome, xml, _ = xml_fornitore
    ricezione.ricevi(nome, xml)
    richiesta = rf.get("/")
    richiesta.user, richiesta.azienda = superuser, noi
    valori = {k["etichetta"]: k["valore"] for k in kpi(richiesta)["kpi"]}
    assert valori["fatture ricevute da verificare"] == 1 and valori["da pagare ai fornitori"].startswith("324")
