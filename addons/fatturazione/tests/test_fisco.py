"""Fisco italiano: XML valido per lo schema ufficiale in ogni caso, incassi parziali, compensazione, DDT."""
import xml.etree.ElementTree as ET
from decimal import Decimal as D
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
from fatturazione.models import CassaPrevidenziale, DatiFiscali, Fattura, Incasso, RigaFattura, RiferimentoDDT, Ritenuta
from fiscale import hooks as fiscale_hooks
from fiscale.models import AliquotaIva, TerminePagamento
from sdi import validazione

NS = {"p": fatturapa.NS}
OGGI = timezone.localdate()


@pytest.fixture
def scena(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    azienda.partita_iva, azienda.indirizzo, azienda.cap, azienda.citta, azienda.provincia = (
        "01234567897", "Via Roma 1", "00100", "Roma", "RM")
    azienda.save()
    DatiFiscali.objects.create(azienda=azienda, iban="IT60X0542811101000000123456", banca="Banca")
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", partita_iva="12345678903", codice_sdi="ABC1234",
                                      indirizzo="Via Po 2", cap="20100", citta="Milano", provincia="MI", cliente=True)
    return azienda, cliente


def _fattura(azienda, cliente, prezzo="1000", codice="22", **extra):
    f = Fattura.objects.create(azienda=azienda, cliente=cliente, **extra)
    RigaFattura.objects.create(fattura=f, descrizione="Consulenza", prezzo=D(prezzo), aliquota=AliquotaIva.objects.get(codice=codice))
    f.ricalcola()
    return f


def _xml(fattura):
    nome, contenuto = fatturapa.genera(fattura)
    errori = validazione.errori(contenuto) if hasattr(validazione, "errori") else validazione.valida(contenuto)
    assert not errori, errori
    return nome, ET.fromstring(contenuto), contenuto


def _testo(radice, percorso):
    return radice.find(percorso, NS).text


def test_professionista_con_cassa_ritenuta_e_bollo_no(scena):
    azienda, cliente = scena
    f = _fattura(azienda, cliente, tipo="TD06")
    CassaPrevidenziale.objects.create(fattura=f, tipo="TC22", aliquota_cassa=D(4), aliquota=AliquotaIva.objects.get(codice="22"), soggetta_ritenuta=True)
    Ritenuta.objects.create(fattura=f, tipo="RT01", aliquota_ritenuta=D(20), causale="A")
    f.ricalcola()
    assert f.imponibile == D("1040.00") and f.imposta == D("228.80") and f.totale == D("1268.80")
    assert f.ritenute == D("208.00") and f.da_incassare == D("1060.80")
    operazioni.emetti(f)
    assert sum(s.importo for s in f.scadenze.all()) == D("1060.80")
    _, radice, _ = _xml(f)
    doc = ".//DatiGeneraliDocumento/"
    assert radice.find(".//TipoDocumento").text == "TD06"
    assert radice.find(".//DatiRitenuta/ImportoRitenuta").text == "208.00"
    assert radice.find(".//DatiCassaPrevidenziale/ImportoContributoCassa").text == "40.00"
    assert radice.find(".//DettaglioLinee/Ritenuta").text == "SI"
    assert radice.find(".//ImportoPagamento").text == "1060.80"
    assert radice.find(".//ImportoTotaleDocumento").text == "1268.80" and doc


def test_agente_enasarco_e_irpef_insieme(scena):
    azienda, cliente = scena
    f = _fattura(azienda, cliente)
    Ritenuta.objects.create(fattura=f, tipo="RT02", aliquota_ritenuta=D("23"), percentuale_base=D(50), causale="R")
    Ritenuta.objects.create(fattura=f, tipo="RT04", aliquota_ritenuta=D("8.5"), causale="R")
    f.ricalcola()
    assert f.ritenute == D("115.00") + D("85.00")
    operazioni.emetti(f)
    assert len(_xml(f)[1].findall(".//DatiRitenuta")) == 2


@pytest.mark.parametrize("codice,atteso", [("N4", "2.00"), ("N2.2", "2.00"), ("N3.5", "2.00"), ("N3.1", "0.00"), ("N6.7", "0.00"), ("22", "0.00")])
def test_bollo_automatico_per_natura(scena, codice, atteso):
    azienda, cliente = scena
    assert _fattura(azienda, cliente, codice=codice).bollo == D(atteso)


def test_bollo_sotto_soglia_e_forzato(scena):
    azienda, cliente = scena
    assert _fattura(azienda, cliente, prezzo="77.47", codice="N4").bollo == 0
    assert _fattura(azienda, cliente, prezzo="77.48", codice="N4").bollo == D(2)
    assert _fattura(azienda, cliente, prezzo="10", bollo_modo="si").bollo == D(2)
    assert _fattura(azienda, cliente, codice="N4", bollo_modo="no").bollo == 0


def test_bollo_nell_xml_e_addebitato_al_cliente(scena):
    azienda, cliente = scena
    f = operazioni.emetti(_fattura(azienda, cliente, codice="N4"))
    radice = _xml(f)[1]
    assert radice.find(".//DatiBollo/BolloVirtuale").text == "SI" and radice.find(".//DatiBollo/ImportoBollo").text == "2.00"
    assert f.totale == D(1000)
    DatiFiscali.objects.filter(azienda=azienda).update(bollo_al_cliente=True)
    addebitato = operazioni.emetti(_fattura(azienda, cliente, codice="N4"))
    assert addebitato.totale == D(1002) and addebitato.righe.filter(is_bollo=True).count() == 1
    assert sum(s.importo for s in addebitato.scadenze.all()) == D(1002)
    _xml(addebitato)


def test_pubblica_amministrazione_fpa12_cig_cup_scissione(scena):
    azienda, _ = scena
    pa = Contatto.objects.create(azienda=azienda, nome="Comune di Roma", codice_fiscale="02438750586", codice_sdi="UF1234",
                                 pubblica_amministrazione=True, indirizzo="Via 1", cap="00100", citta="Roma", provincia="RM")
    f = _fattura(azienda, pa, codice="22S", rif_tipo="contratto", rif_numero="C-55", rif_data=OGGI, cig="1234567890", cup="B12C34000000001")
    operazioni.emetti(f)
    assert sum(s.importo for s in f.scadenze.all()) == D(1000)
    nome, radice, _ = _xml(f)
    assert radice.get("versione") == "FPA12" and radice.find(".//FormatoTrasmissione").text == "FPA12"
    assert radice.find(".//CodiceDestinatario").text == "UF1234"
    assert radice.find(".//DatiContratto/CodiceCIG").text == "1234567890" and radice.find(".//DatiContratto/CodiceCUP").text == "B12C34000000001"
    assert radice.find(".//EsigibilitaIVA").text == "S" and radice.find(".//ImportoPagamento").text == "1000.00"
    assert radice.find(".//ImportoTotaleDocumento").text == "1220.00"


def test_pa_senza_codice_ufficio_non_si_emette(scena):
    azienda, _ = scena
    pa = Contatto.objects.create(azienda=azienda, nome="Comune", codice_fiscale="02438750586", pubblica_amministrazione=True)
    with pytest.raises(ValidationError, match="univoco ufficio"):
        operazioni.emetti(_fattura(azienda, pa))


def test_cig_senza_documento_si_ferma(scena):
    azienda, cliente = scena
    with pytest.raises(ValidationError, match="CIG"):
        operazioni.emetti(_fattura(azienda, cliente, cig="1234567890"))


def test_autofattura_reverse_charge_estero_ruoli_invertiti_e_serie_propria(scena):
    azienda, _ = scena
    tedesco = Contatto.objects.create(azienda=azienda, nome="Müller GmbH", nazione="DE", partita_iva="811907980", indirizzo="Hauptstr. 1", citta="Berlin", fornitore=True)
    f = _fattura(azienda, tedesco, tipo="TD17")
    with pytest.raises(ValidationError, match="fattura del fornitore"):
        operazioni.emetti(f)
    f.collegata_numero, f.collegata_data = "INV-9", OGGI
    f.save()
    operazioni.emetti(f)
    assert f.numero.startswith("AF") and f.pagata and not f.scadenze.exists()
    _, radice, _ = _xml(f)
    assert radice.find(".//CedentePrestatore//IdCodice").text == "811907980" and radice.find(".//CedentePrestatore//IdPaese").text == "DE"
    assert radice.find(".//CedentePrestatore//RegimeFiscale").text == "RF18" and radice.find(".//CedentePrestatore/Sede/CAP").text == "00000"
    assert radice.find(".//CessionarioCommittente//IdCodice").text == azienda.partita_iva
    assert radice.find(".//CodiceDestinatario").text == "0000000" and radice.find(".//DatiFattureCollegate/IdDocumento").text == "INV-9"


def test_reverse_charge_attivo_edile(scena):
    azienda, cliente = scena
    f = operazioni.emetti(_fattura(azienda, cliente, codice="N6.3"))
    assert f.imposta == 0 and f.bollo == 0
    assert _xml(f)[1].find(".//DatiRiepilogo/Natura").text == "N6.3"


@pytest.mark.parametrize("nazione,piva,codice,destinatario", [("DE", "811907980", "811907980", "XXXXXXX"), ("US", "", "OO99999999999", "XXXXXXX"),
                                                              ("FR", "", "0000000", "XXXXXXX"), ("SM", "SM12345", "SM12345", "2R4GTO8")])
def test_clienti_esteri(scena, nazione, piva, codice, destinatario):
    azienda, _ = scena
    estero = Contatto.objects.create(azienda=azienda, nome="Estero", nazione=nazione, partita_iva=piva, indirizzo="Street 1", citta="City")
    f = operazioni.emetti(_fattura(azienda, estero, codice="N3.1"))
    radice = _xml(f)[1]
    assert radice.find(".//CessionarioCommittente//IdCodice").text == codice and radice.find(".//CodiceDestinatario").text == destinatario


@pytest.mark.parametrize("tipo", ["TD02", "TD03", "TD05", "TD26"])
def test_altri_tipi_documento(scena, tipo):
    azienda, cliente = scena
    f = operazioni.emetti(_fattura(azienda, cliente, tipo=tipo))
    assert f.scadenze.exists() and _xml(f)[1].find(".//TipoDocumento").text == tipo


def test_fattura_differita_vuole_il_ddt_e_lo_scrive(scena):
    azienda, cliente = scena
    f = _fattura(azienda, cliente, tipo="TD24")
    with pytest.raises(ValidationError, match="DDT"):
        operazioni.emetti(f)
    RiferimentoDDT.objects.create(fattura=f, numero="DDT-1", data=OGGI)
    operazioni.emetti(f)
    assert _xml(f)[1].find(".//DatiDDT/NumeroDDT").text == "DDT-1"


def _emessa_a_rate(azienda, cliente):
    termine, _ = TerminePagamento.objects.get_or_create(nome="Due rate", defaults={"rate": [{"giorni": 30, "percentuale": 50}, {"giorni": 60, "percentuale": 50}]})
    return operazioni.emetti(_fattura(azienda, cliente, termine_pagamento=termine))


def test_incassi_parziali_su_piu_rate(scena):
    azienda, cliente = scena
    f = _emessa_a_rate(azienda, cliente)
    prima, seconda = f.scadenze.order_by("data")
    operazioni.incassa_fattura(f, D("100"), OGGI, riferimento="CRO1")
    prima.refresh_from_db(); f.refresh_from_db()
    assert prima.incassato == D(100) and not prima.pagata and not f.pagata and f.residuo == D(1120)
    operazioni.incassa_fattura(f, D("700"))
    prima.refresh_from_db(); seconda.refresh_from_db()
    assert prima.pagata and seconda.incassato == D(190) and not seconda.pagata and f.percentuale_incassata == 65
    with pytest.raises(ValidationError, match="Restano"):
        operazioni.incassa_fattura(f, D("421"))
    operazioni.incassa_fattura(f, D("420"), tipo=Incasso.ABBUONO)
    f.refresh_from_db()
    assert f.pagata and f.residuo == 0


def test_annullo_incasso_riapre(scena):
    azienda, cliente = scena
    f = _emessa_a_rate(azienda, cliente)
    for s in f.scadenze.all():
        operazioni.incassa(s)
    f.refresh_from_db()
    assert f.pagata
    operazioni.annulla_incasso(Incasso.objects.first())
    f.refresh_from_db()
    assert not f.pagata and f.scadenze.filter(pagata=False, pagata_il=None).count() == 1


def test_pagine_incasso(client, superuser, scena):
    azienda, cliente = scena
    f = _emessa_a_rate(azienda, cliente)
    pagina = client.get(f"/fatturazione/fatture/{f.pk}/").content.decode()
    assert "ft-anello" in pagina and "Registra" in pagina
    client.post(f"/fatturazione/fatture/{f.pk}/incasso/", {"importo": "200.50", "data": OGGI.isoformat(), "metodo": "carta"})
    voce = Incasso.objects.get()
    assert voce.importo == D("200.50") and voce.metodo == "carta" and voce.utente == superuser
    assert client.get("/fatturazione/incassi/").status_code == 200
    r = client.post(f"/fatturazione/fatture/{f.pk}/incasso/", {"importo": "9999", "data": OGGI.isoformat()}, follow=True)
    assert "Restano da incassare" in r.content.decode() and Incasso.objects.count() == 1
    client.post(f"/fatturazione/incassi/{voce.pk}/annulla/")
    assert not Incasso.objects.exists()


def test_nota_di_credito_compensa_le_scadenze(scena):
    azienda, cliente = scena
    f = _emessa_a_rate(azienda, cliente)
    operazioni.emetti(operazioni.nota_di_credito(f))
    f.refresh_from_db()
    assert f.pagata and f.residuo == 0 and Incasso.objects.filter(tipo=Incasso.COMPENSAZIONE).count() == 2


def test_nota_parziale_e_gia_incassata(scena):
    azienda, cliente = scena
    f = _emessa_a_rate(azienda, cliente)
    operazioni.incassa_fattura(f, D("1220"))
    nota = operazioni.emetti(operazioni.nota_di_credito(f))
    assert operazioni.da_rimborsare(nota) == D(1220)               # già pagata: si restituisce, non si compensa
    g = _emessa_a_rate(azienda, cliente)
    nota = operazioni.nota_di_credito(g)
    riga = nota.righe.get()
    riga.prezzo = D("100")
    riga.save()
    nota.ricalcola()
    operazioni.emetti(nota)
    assert g.residuo == D(1098) and not g.scadenze.filter(data=g.scadenze.order_by("data").first().data, incassato__gt=0).exists()


def test_nota_copia_ritenute_e_casse(scena):
    azienda, cliente = scena
    f = _fattura(azienda, cliente, tipo="TD06")
    CassaPrevidenziale.objects.create(fattura=f, tipo="TC22", aliquota_cassa=D(4), aliquota=AliquotaIva.objects.get(codice="22"))
    Ritenuta.objects.create(fattura=f, tipo="RT01", aliquota_ritenuta=D(20), causale="A")
    f.ricalcola()
    operazioni.emetti(f)
    nota = operazioni.emetti(operazioni.nota_di_credito(f))
    assert nota.totale == f.totale and nota.ritenute == f.ritenute
    _xml(nota)
    f.refresh_from_db()
    assert f.pagata


def test_fattura_differita_da_consegne(scena):
    from magazzino import collegamenti
    from magazzino import operazioni as magazzino
    from magazzino.models import Consegna, Magazzino, RigaConsegna
    from prodotti.models import Prodotto
    from vendite.models import OrdineVendita, RigaVendita
    azienda, cliente = scena
    bene = Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=D(200))
    Magazzino.objects.get_or_create(azienda=azienda, defaults={"nome": "Sede", "predefinito": True})
    ordine = OrdineVendita.objects.create(azienda=azienda, cliente=cliente, stato="confermato", numero_ordine="SO/1")
    RigaVendita.objects.create(ordine=ordine, prodotto=bene, quantita=D(3), prezzo=D(150))
    prima = collegamenti.consegna_da_ordine(OrdineVendita, ordine)
    with pytest.raises(ValidationError, match="spedite"):
        operazioni.da_consegne([prima])
    magazzino.spedisci(prima)
    libera = Consegna.objects.create(azienda=azienda, magazzino=prima.magazzino, cliente=cliente)
    RigaConsegna.objects.create(consegna=libera, prodotto=bene, quantita=D(1))
    magazzino.spedisci(libera)
    f = operazioni.da_consegne([prima, libera])
    assert f.tipo == "TD24" and f.ddt.count() == 2 and f.imponibile == D(650)
    with pytest.raises(ValidationError, match="già in"):
        operazioni.da_consegne([prima])
    operazioni.emetti(f)
    assert len(_xml(f)[1].findall(".//DatiDDT")) == 2


def test_aggiornamento_aggiunge_le_aliquote_nuove(scena):
    AliquotaIva.objects.filter(codice="22S").delete()
    AliquotaIva.objects.filter(codice="22").update(descrizione="Modificata dall'azienda")
    fiscale_hooks.post_upgrade(None, "1.0.0")
    assert AliquotaIva.objects.get(codice="22S").esigibilita == "S"
    assert AliquotaIva.objects.get(codice="22").descrizione == "Modificata dall'azienda"
