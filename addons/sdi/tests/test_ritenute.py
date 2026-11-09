"""Ritenute d'acconto sulle fatture ricevute: lette dall'XML (solo RT01 e RT02), rilette per le fatture di prima,
per mese di pagamento in proporzione al pagato, codici tributo, CU dell'anno, pagina, CSV e pacchetto per lo studio."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Azienda
from sdi import passive, ritenute
from sdi.models import FatturaPassiva

NOI = "01234567897"
ANNO = timezone.localdate().year


def _xml(numero="7", causale="A", tipo="RT01", extra=""):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:FatturaElettronica versione="FPR12" xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">
<FatturaElettronicaHeader>
 <CedentePrestatore><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>12345678903</IdCodice></IdFiscaleIVA>
  <CodiceFiscale>BNCLRA80A41H501X</CodiceFiscale><Anagrafica><Nome>Laura</Nome><Cognome>Bianchi</Cognome></Anagrafica></DatiAnagrafici>
  <Sede><Indirizzo>Via Po 1</Indirizzo><CAP>10100</CAP><Comune>Torino</Comune><Nazione>IT</Nazione></Sede></CedentePrestatore>
 <CessionarioCommittente><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>{NOI}</IdCodice></IdFiscaleIVA>
  <Anagrafica><Denominazione>Noi Srl</Denominazione></Anagrafica></DatiAnagrafici></CessionarioCommittente>
</FatturaElettronicaHeader>
<FatturaElettronicaBody>
 <DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD06</TipoDocumento><Divisa>EUR</Divisa><Data>{ANNO}-01-15</Data><Numero>{numero}</Numero>
  <DatiRitenuta><TipoRitenuta>{tipo}</TipoRitenuta><ImportoRitenuta>208.00</ImportoRitenuta><AliquotaRitenuta>20.00</AliquotaRitenuta><CausalePagamento>{causale}</CausalePagamento></DatiRitenuta>
  {extra}
  <DatiCassaPrevidenziale><TipoCassa>TC22</TipoCassa><AlCassa>4.00</AlCassa><ImportoContributoCassa>40.00</ImportoContributoCassa><ImponibileCassa>1000.00</ImponibileCassa><AliquotaIVA>22.00</AliquotaIVA></DatiCassaPrevidenziale>
  <ImportoTotaleDocumento>1268.80</ImportoTotaleDocumento></DatiGeneraliDocumento></DatiGenerali>
 <DatiBeniServizi><DettaglioLinee><NumeroLinea>1</NumeroLinea><Descrizione>Consulenza</Descrizione><PrezzoUnitario>1000.00</PrezzoUnitario><PrezzoTotale>1000.00</PrezzoTotale><AliquotaIVA>22.00</AliquotaIVA></DettaglioLinee>
  <DatiRiepilogo><AliquotaIVA>22.00</AliquotaIVA><ImponibileImporto>1040.00</ImponibileImporto><Imposta>228.80</Imposta></DatiRiepilogo></DatiBeniServizi>
 <DatiPagamento><CondizioniPagamento>TP01</CondizioniPagamento>
  <DettaglioPagamento><ModalitaPagamento>MP05</ModalitaPagamento><DataScadenzaPagamento>{ANNO}-02-15</DataScadenzaPagamento><ImportoPagamento>530.40</ImportoPagamento></DettaglioPagamento>
  <DettaglioPagamento><ModalitaPagamento>MP05</ModalitaPagamento><DataScadenzaPagamento>{ANNO}-03-15</DataScadenzaPagamento><ImportoPagamento>530.40</ImportoPagamento></DettaglioPagamento></DatiPagamento>
</FatturaElettronicaBody></p:FatturaElettronica>""".encode()


@pytest.fixture
def noi(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    azienda = Azienda.objects.get(pk=1)
    azienda.partita_iva = NOI
    azienda.save()
    return azienda


def _paga(f, *date):
    for s, d in zip(f.scadenze.order_by("pk"), date):
        passive.paga(s, d)


def test_letta_dall_xml_e_proporzionale_al_pagato(noi):
    (f, _), = passive.importa("IT12345678903_00007.xml", _xml())
    assert (f.ritenuta, f.base_ritenuta, f.aliquota_ritenuta, f.causale_ritenuta, f.contributo_cassa) == (
        Decimal("208.00"), Decimal("1040.00"), Decimal("20.00"), "A", Decimal("40.00"))
    _paga(f, datetime.date(ANNO, 2, 20), datetime.date(ANNO, 3, 18))
    righe = ritenute.operate(FatturaPassiva.objects.all(), ANNO)
    assert [(r.mese, r.ritenuta, r.soggetto, r.codice) for r in righe] == [(2, Decimal("104.00"), Decimal("520.00"), "1040"),
                                                                           (3, Decimal("104.00"), Decimal("520.00"), "1040")]
    assert ritenute.per_f24(righe) == {(2, "1040"): Decimal("104.00"), (3, "1040"): Decimal("104.00")}
    (fornitore, causale, soggetto, non_soggetto, ritenuta, cassa), = ritenute.per_cu(righe)
    assert (causale, soggetto, non_soggetto, ritenuta, cassa) == ("A", Decimal("1040.00"), Decimal("0.00"), Decimal("208.00"), Decimal("40.00"))
    assert [r.mese for r in ritenute.operate(FatturaPassiva.objects.all(), ANNO, 3)] == [3]


def test_contributi_non_sono_ritenute_e_provvigioni(noi):
    enasarco = "<DatiRitenuta><TipoRitenuta>RT04</TipoRitenuta><ImportoRitenuta>50.00</ImportoRitenuta><AliquotaRitenuta>8.50</AliquotaRitenuta><CausalePagamento>R</CausalePagamento></DatiRitenuta>"
    (f, _), = passive.importa("IT12345678903_00008.xml", _xml("8", causale="R", extra=enasarco))
    assert f.ritenuta == Decimal("208.00") and f.causale_ritenuta == "R"
    assert ritenute.codice_tributo("R", "RT01") == "1038" and ritenute.codice_tributo("M", "RT01") == "1040"
    (g, _), = passive.importa("IT12345678903_00009.xml", _xml("9", tipo="RT03"))           # solo un contributo INPS
    assert g.ritenuta == 0


def test_fatture_di_prima_si_rileggono(noi):
    (f, _), = passive.importa("IT12345678903_00007.xml", _xml())
    FatturaPassiva.objects.filter(pk=f.pk).update(ritenuta=0, base_ritenuta=0, causale_ritenuta="", ritenuta_letta=False)
    assert ritenute.aggiorna(FatturaPassiva.objects.all()) == 1
    f.refresh_from_db()
    assert f.ritenuta == Decimal("208.00") and f.ritenuta_letta and ritenute.aggiorna(FatturaPassiva.objects.all()) == 0


def test_pagina_csv_e_pacchetto(client, noi):
    (f, _), = passive.importa("IT12345678903_00007.xml", _xml())
    _paga(f, datetime.date(ANNO, 2, 20))
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get(f"/sdi/ritenute/?anno={ANNO}&mese=").content.decode()
    assert "Bianchi" in html and "104,00" in html and f"Per la CU {ANNO + 1}" in html and "codice 1040" in html
    csv = client.get(f"/sdi/ritenute/?anno={ANNO}&mese=&formato=csv").content.decode("utf-8-sig")
    assert "Causale CU" in csv and "BNCLRA80A41H501X" in csv and "104,00" in csv
    from sdi.per_commercialista import acquisti
    richiesta = type("R", (), {"user": User.objects.get(username="root"), "azienda": noi})()
    file = dict(acquisti(richiesta, ANNO, 2, []))
    assert "acquisti/ritenute-operate.csv" in file
