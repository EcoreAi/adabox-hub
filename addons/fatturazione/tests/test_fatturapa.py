"""Fattura elettronica: validazione strutturale (elementi obbligatori, coerenza dei totali) e registro IVA."""
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
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

ANNO = timezone.localdate().year
NS = {"p": fatturapa.NS}

OBBLIGATORI = [
    "FatturaElettronicaHeader/DatiTrasmissione/IdTrasmittente/IdPaese",
    "FatturaElettronicaHeader/DatiTrasmissione/IdTrasmittente/IdCodice",
    "FatturaElettronicaHeader/DatiTrasmissione/ProgressivoInvio",
    "FatturaElettronicaHeader/DatiTrasmissione/FormatoTrasmissione",
    "FatturaElettronicaHeader/DatiTrasmissione/CodiceDestinatario",
    "FatturaElettronicaHeader/CedentePrestatore/DatiAnagrafici/IdFiscaleIVA/IdCodice",
    "FatturaElettronicaHeader/CedentePrestatore/DatiAnagrafici/Anagrafica/Denominazione",
    "FatturaElettronicaHeader/CedentePrestatore/DatiAnagrafici/RegimeFiscale",
    "FatturaElettronicaHeader/CedentePrestatore/Sede/Indirizzo",
    "FatturaElettronicaHeader/CedentePrestatore/Sede/CAP",
    "FatturaElettronicaHeader/CedentePrestatore/Sede/Comune",
    "FatturaElettronicaHeader/CedentePrestatore/Sede/Nazione",
    "FatturaElettronicaHeader/CessionarioCommittente/DatiAnagrafici/Anagrafica/Denominazione",
    "FatturaElettronicaHeader/CessionarioCommittente/Sede/Indirizzo",
    "FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/TipoDocumento",
    "FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/Divisa",
    "FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/Data",
    "FatturaElettronicaBody/DatiGenerali/DatiGeneraliDocumento/Numero",
    "FatturaElettronicaBody/DatiBeniServizi/DettaglioLinee",
    "FatturaElettronicaBody/DatiBeniServizi/DatiRiepilogo",
]


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    azienda.nome, azienda.partita_iva, azienda.indirizzo = "Ichnobyte Srl", "01234567897", "Via Roma 1"
    azienda.cap, azienda.citta, azienda.provincia = "00100", "Roma", "rm"
    azienda.save()
    DatiFiscali.objects.create(azienda=azienda, iban="IT60 X054 2811 1010 0000 0123 456", banca="Banca Demo",
                               rea_ufficio="RM", rea_numero="123456", capitale_sociale=Decimal("10000"),
                               socio_unico="SM")
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, partita_iva="12345678903",
                                      codice_sdi="ABC1234", indirizzo="Corso Italia 5", cap="20100", citta="Milano",
                                      provincia="MI", email="a@rossi.it")
    monitor = Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=Decimal("199.99"))
    corso = Prodotto.objects.create(azienda=azienda, nome="Corso", tipo="servizio", prezzo_vendita=Decimal("100"),
                                    aliquota_iva=AliquotaIva.objects.get(codice="N4"))
    f = Fattura.objects.create(azienda=azienda, cliente=cliente, causale="Fornitura",
                               termine_pagamento=TerminePagamento.objects.get(nome__icontains="30-60"))
    RigaFattura.objects.create(fattura=f, prodotto=monitor, quantita=3, sconto=10)
    RigaFattura.objects.create(fattura=f, prodotto=corso)
    RigaFattura.objects.create(fattura=f, descrizione="Trasporto", prezzo=Decimal("15"))
    f.ricalcola()
    operazioni.emetti(f)
    return azienda, cliente, f


def _xml(fattura):
    nome, contenuto = fatturapa.genera(fattura)
    return nome, ET.fromstring(contenuto)


def _testo(radice, percorso):
    return radice.find(percorso).text


def test_struttura_e_totali(scena):
    _, _, f = scena
    nome, radice = _xml(f)
    assert nome == "IT01234567897_00001.xml"
    assert radice.tag == f"{{{fatturapa.NS}}}FatturaElettronica" and radice.get("versione") == "FPR12"
    for percorso in OBBLIGATORI:
        assert radice.find(percorso) is not None, percorso
    assert _testo(radice, ".//DatiGeneraliDocumento/Numero") == f"1/{ANNO}"
    assert _testo(radice, ".//DatiTrasmissione/CodiceDestinatario") == "ABC1234"
    assert _testo(radice, ".//CedentePrestatore/Sede/Provincia") == "RM"
    linee = radice.findall(".//DettaglioLinee")
    assert [_testo(x, "PrezzoTotale") for x in linee] == ["539.97", "100.00", "15.00"]
    assert linee[0].find("ScontoMaggiorazione/Percentuale").text == "10.00"
    assert linee[1].find("Natura").text == "N4" and linee[0].find("Natura") is None
    riepiloghi = radice.findall(".//DatiRiepilogo")
    assert [(_testo(r, "AliquotaIVA"), r.findtext("Natura")) for r in riepiloghi] == [("22.00", None), ("0.00", "N4")]
    assert riepiloghi[0].findtext("EsigibilitaIVA") == "I" and riepiloghi[1].findtext("RiferimentoNormativo")
    # coerenza: somma delle linee = imponibili del riepilogo; imponibili + imposte = totale documento
    for r in riepiloghi:
        somma = sum(Decimal(x.findtext("PrezzoTotale")) for x in linee
                    if x.findtext("AliquotaIVA") == r.findtext("AliquotaIVA") and x.findtext("Natura") == r.findtext("Natura"))
        assert somma == Decimal(r.findtext("ImponibileImporto"))
    totale = sum(Decimal(r.findtext("ImponibileImporto")) + Decimal(r.findtext("Imposta")) for r in riepiloghi)
    assert totale == Decimal(_testo(radice, ".//ImportoTotaleDocumento")) == f.totale
    pagamenti = radice.findall(".//DettaglioPagamento")
    assert _testo(radice, ".//CondizioniPagamento") == "TP01" and len(pagamenti) == 2
    assert sum(Decimal(p.findtext("ImportoPagamento")) for p in pagamenti) == f.totale
    assert pagamenti[0].findtext("IBAN") == "IT60X0542811101000000123456"
    assert _testo(radice, ".//IscrizioneREA/StatoLiquidazione") == "LN"


def test_progressivo_assegnato_una_volta(scena):
    azienda, cliente, f = scena
    assert _xml(f)[0] == _xml(f)[0] == "IT01234567897_00001.xml"
    nota = operazioni.nota_di_credito(f)
    operazioni.emetti(nota)
    nome, radice = _xml(nota)
    assert nome == "IT01234567897_00002.xml" and _testo(radice, ".//TipoDocumento") == "TD04"
    assert _testo(radice, ".//DatiFattureCollegate/IdDocumento") == f.numero
    assert radice.find(".//DatiPagamento") is None


def test_privato_senza_codice_sdi(scena):
    azienda, _, _ = scena
    privato = Contatto.objects.create(azienda=azienda, nome="Mario Bianchi", codice_fiscale="RSSMRA80A01H501U",
                                      pec="mario@pec.it", indirizzo="Via Po 3", cap="10100", citta="Torino")
    f = Fattura.objects.create(azienda=azienda, cliente=privato)
    RigaFattura.objects.create(fattura=f, descrizione="Riparazione", prezzo=Decimal("50"))
    f.ricalcola()
    operazioni.emetti(f)
    _, radice = _xml(f)
    assert _testo(radice, ".//CodiceDestinatario") == "0000000" and _testo(radice, ".//PECDestinatario") == "mario@pec.it"
    cess = radice.find(".//CessionarioCommittente/DatiAnagrafici")
    assert cess.find("IdFiscaleIVA") is None and cess.findtext("CodiceFiscale") == "RSSMRA80A01H501U"


def test_dati_mancanti(scena):
    azienda, cliente, f = scena
    bozza = Fattura.objects.create(azienda=azienda, cliente=cliente)
    with pytest.raises(ValidationError, match="non è emessa"):
        fatturapa.genera(bozza)
    DatiFiscali.objects.all().delete()
    cliente.indirizzo = ""
    cliente.save()
    f.refresh_from_db()
    problemi = fatturapa.errori(f)
    assert any("dati fiscali" in p for p in problemi) and any("del cliente" in p for p in problemi)


def test_bottone_scarica_xml(client, superuser, scena):
    _, _, f = scena
    r = client.post(f"/fatturazione/fatture/{f.pk}/bottone/xml/")
    assert r.status_code == 200 and r["Content-Type"] == "application/xml"
    assert 'filename="IT01234567897_00001.xml"' in r["Content-Disposition"]
    assert b"<FatturaElettronicaHeader>" in r.content


def test_registro_iva(client, superuser, scena):
    azienda, cliente, f = scena
    nota = operazioni.nota_di_credito(f)
    nota.righe.exclude(descrizione="Trasporto").delete()
    nota.ricalcola()
    operazioni.emetti(nota)
    oggi = timezone.localdate()
    html = client.get(f"/fatturazione/registro-iva/?anno={oggi.year}&mese={oggi.month}").content.decode()
    assert f"1/{ANNO}" in html and f"2/{ANNO}" in html and "nota di credito" in html
    # imponibile 22%: 539,97 + 15 − 15 (nota) = 539,97; esente 100
    assert "539,97" in html and "-15,00" in html
    csv = client.get(f"/fatturazione/registro-iva/?anno={oggi.year}&mese=&formato=csv").content.decode()
    assert csv.startswith("Data;Numero") and csv.count("\n") == 4
