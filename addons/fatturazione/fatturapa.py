"""Fattura elettronica FatturaPA 1.2 (FPR12 tra privati, FPA12 verso la Pubblica Amministrazione): XML e nome del file.

Struttura secondo le specifiche tecniche dell'Agenzia delle Entrate; lo schema XSD ufficiale e l'invio allo SDI
sono del modulo `sdi` (spec fase 5, decisione 9)."""
import xml.etree.ElementTree as ET
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from contatti.validatori import UE
from prodotti.models import codice_cliente

from .models import DatiFiscali, Fattura

SAN_MARINO = "2R4GTO8"
NS = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
ET.register_namespace("p", NS)


def _d(valore, cifre=2):
    return f"{Decimal(valore):.{cifre}f}"


def _sub(padre, tag, testo=None):
    el = ET.SubElement(padre, tag)
    if testo is not None:
        el.text = str(testo)
    return el


def _sede(padre, s):
    sede = _sub(padre, "Sede")
    _sub(sede, "Indirizzo", s.indirizzo[:60])
    _sub(sede, "CAP", s.cap if getattr(s, "nazione", "IT") == "IT" else "00000")
    _sub(sede, "Comune", s.citta[:60])
    if s.provincia and getattr(s, "nazione", "IT") == "IT":
        _sub(sede, "Provincia", s.provincia.upper())
    _sub(sede, "Nazione", getattr(s, "nazione", "IT") or "IT")


def errori(fattura):
    """Dati mancanti per un XML accettabile dallo SDI."""
    az, cl = fattura.azienda, fattura.cliente
    mancano = []
    if fattura.stato != Fattura.EMESSA:
        mancano.append("La fattura non è emessa.")
    if not DatiFiscali.objects.filter(azienda=az).exists():
        mancano.append(f"Mancano i dati fiscali di {az} (regime fiscale).")
    if not az.partita_iva:
        mancano.append(f"Manca la partita IVA di {az}.")
    for chi, obj in (("dell'azienda", az), ("del cliente", cl)):
        if not (obj.indirizzo and obj.citta and (obj.cap or getattr(obj, "nazione", "IT") != "IT")):
            mancano.append(f"Manca l'indirizzo completo (via, CAP, città) {chi}.")
    if (cl.nazione or "IT") == "IT" and not (cl.partita_iva or cl.codice_fiscale):
        mancano.append("Il cliente non ha né partita IVA né codice fiscale.")
    if cl.pubblica_amministrazione and len(cl.codice_sdi) != 6:
        mancano.append("Per la Pubblica Amministrazione serve il codice univoco ufficio di 6 caratteri.")
    return mancano


def nome_file(fattura):
    return f"IT{fattura.azienda.partita_iva}_{fattura.progressivo_invio}.xml"


@transaction.atomic
def assegna_progressivo(fattura):
    """Progressivo di invio univoco per azienda (5 cifre), assegnato una volta sola."""
    if not fattura.progressivo_invio:
        dati = DatiFiscali.objects.select_for_update().get(azienda=fattura.azienda)
        dati.progressivo_invio = dati.progressivo_invio % 99999 + 1
        dati.save(update_fields=["progressivo_invio"])
        fattura.progressivo_invio = f"{dati.progressivo_invio:05d}"
        fattura.save(update_fields=["progressivo_invio"])
    return fattura.progressivo_invio


def _id_fiscale(anag, contatto):
    """IdFiscaleIVA di un contatto: all'estero senza partita IVA valgono i codici convenzionali dello SDI."""
    nazione = contatto.nazione or "IT"
    codice = contatto.partita_iva or ("" if nazione == "IT" else ("0000000" if nazione in UE else "OO99999999999"))
    if codice:
        idf = _sub(anag, "IdFiscaleIVA")
        _sub(idf, "IdPaese", nazione)
        _sub(idf, "IdCodice", codice)
    if contatto.codice_fiscale and nazione == "IT":
        _sub(anag, "CodiceFiscale", contatto.codice_fiscale.upper())


def _cedente_azienda(testata, az, dati):
    cedente = _sub(testata, "CedentePrestatore")
    anag = _sub(cedente, "DatiAnagrafici")
    idf = _sub(anag, "IdFiscaleIVA")
    _sub(idf, "IdPaese", "IT")
    _sub(idf, "IdCodice", az.partita_iva)
    if az.codice_fiscale:
        _sub(anag, "CodiceFiscale", az.codice_fiscale.upper())
    _sub(_sub(anag, "Anagrafica"), "Denominazione", az.nome[:80])
    _sub(anag, "RegimeFiscale", dati.regime_fiscale)
    _sede(cedente, az)
    if dati.rea_ufficio and dati.rea_numero:
        rea = _sub(cedente, "IscrizioneREA")
        _sub(rea, "Ufficio", dati.rea_ufficio.upper())
        _sub(rea, "NumeroREA", dati.rea_numero)
        if dati.capitale_sociale is not None:
            _sub(rea, "CapitaleSociale", _d(dati.capitale_sociale))
        if dati.socio_unico:
            _sub(rea, "SocioUnico", dati.socio_unico)
        _sub(rea, "StatoLiquidazione", "LN")


def _cedente_contatto(testata, cl):
    """Autofattura: il fornitore è il cedente, con il regime «altro» come chiedono le regole dello SDI."""
    cedente = _sub(testata, "CedentePrestatore")
    anag = _sub(cedente, "DatiAnagrafici")
    _id_fiscale(anag, cl)
    _sub(_sub(anag, "Anagrafica"), "Denominazione", cl.nome[:80])
    _sub(anag, "RegimeFiscale", "RF18")
    _sede(cedente, cl)


def _cessionario_contatto(testata, cl):
    cessionario = _sub(testata, "CessionarioCommittente")
    anag = _sub(cessionario, "DatiAnagrafici")
    _id_fiscale(anag, cl)
    _sub(_sub(anag, "Anagrafica"), "Denominazione", cl.nome[:80])
    _sede(cessionario, cl)


def _cessionario_azienda(testata, az):
    cessionario = _sub(testata, "CessionarioCommittente")
    anag = _sub(cessionario, "DatiAnagrafici")
    idf = _sub(anag, "IdFiscaleIVA")
    _sub(idf, "IdPaese", "IT")
    _sub(idf, "IdCodice", az.partita_iva)
    if az.codice_fiscale:
        _sub(anag, "CodiceFiscale", az.codice_fiscale.upper())
    _sub(_sub(anag, "Anagrafica"), "Denominazione", az.nome[:80])
    _sede(cessionario, az)


def _codice_destinatario(fattura, cl):
    if fattura.tipo in Fattura.SCAMBIO_RUOLI:
        return "0000000"                 # l'autofattura torna a noi dal cassetto fiscale
    nazione = cl.nazione or "IT"
    if nazione == "SM":
        return SAN_MARINO
    if nazione != "IT":
        return "XXXXXXX"
    return (cl.codice_sdi or "0000000").upper()


def _riferimento(generali, tag, numero, data=None, fattura=None):
    nodo = _sub(generali, tag)
    _sub(nodo, "IdDocumento", numero[:20])
    if data:
        _sub(nodo, "Data", data.isoformat())
    if fattura is not None:
        if fattura.commessa:
            _sub(nodo, "CodiceCommessaConvenzione", fattura.commessa[:100])
        if fattura.cup:
            _sub(nodo, "CodiceCUP", fattura.cup.upper())
        if fattura.cig:
            _sub(nodo, "CodiceCIG", fattura.cig.upper())


def _riferimenti(generali, fattura):
    """In ordine di schema: ordine, contratto, convenzione, ricezione, fatture collegate, DDT."""
    tag_rif = {"ordine": "DatiOrdineAcquisto", "contratto": "DatiContratto", "convenzione": "DatiConvenzione",
               "ricezione": "DatiRicezione"}
    per_tag = {}
    if fattura.rif_numero:
        per_tag[tag_rif.get(fattura.rif_tipo, "DatiOrdineAcquisto")] = (fattura.rif_numero, fattura.rif_data, fattura)
    elif fattura.ordine_id and fattura.ordine.numero_ordine and not fattura.fattura_origine_id:
        per_tag["DatiOrdineAcquisto"] = (fattura.ordine.riferimento_cliente or fattura.ordine.numero_ordine,
                                         fattura.ordine.confermato_il or fattura.ordine.data, None)
    for tag in tag_rif.values():
        if tag in per_tag:
            _riferimento(generali, tag, *per_tag[tag])
    if fattura.fattura_origine_id:
        _riferimento(generali, "DatiFattureCollegate", fattura.fattura_origine.numero, fattura.fattura_origine.data)
    elif fattura.collegata_numero:
        _riferimento(generali, "DatiFattureCollegate", fattura.collegata_numero, fattura.collegata_data)
    for ddt in fattura.ddt.all():
        nodo = _sub(generali, "DatiDDT")
        _sub(nodo, "NumeroDDT", ddt.numero[:20])
        _sub(nodo, "DataDDT", ddt.data.isoformat())


def genera(fattura):
    """(nome del file, XML in bytes). ValidationError se mancano dati."""
    problemi = errori(fattura)
    if problemi:
        raise ValidationError(problemi)
    assegna_progressivo(fattura)
    az, cl, dati = fattura.azienda, fattura.cliente, fattura.azienda.dati_fiscali
    formato = "FPA12" if cl.pubblica_amministrazione and fattura.tipo not in Fattura.SCAMBIO_RUOLI else "FPR12"
    radice = ET.Element(f"{{{NS}}}FatturaElettronica", {"versione": formato})

    testata = _sub(radice, "FatturaElettronicaHeader")
    tx = _sub(testata, "DatiTrasmissione")
    idt = _sub(tx, "IdTrasmittente")
    _sub(idt, "IdPaese", "IT")
    _sub(idt, "IdCodice", az.codice_fiscale or az.partita_iva)
    _sub(tx, "ProgressivoInvio", fattura.progressivo_invio)
    _sub(tx, "FormatoTrasmissione", formato)
    destinatario = _codice_destinatario(fattura, cl)
    _sub(tx, "CodiceDestinatario", destinatario)
    if destinatario == "0000000" and cl.pec and (cl.nazione or "IT") == "IT" and fattura.tipo not in Fattura.SCAMBIO_RUOLI:
        _sub(tx, "PECDestinatario", cl.pec)

    if fattura.tipo in Fattura.SCAMBIO_RUOLI:
        _cedente_contatto(testata, cl)
        _cessionario_azienda(testata, az)
    else:
        _cedente_azienda(testata, az, dati)
        _cessionario_contatto(testata, cl)

    corpo = _sub(radice, "FatturaElettronicaBody")
    generali = _sub(corpo, "DatiGenerali")
    doc = _sub(generali, "DatiGeneraliDocumento")
    _sub(doc, "TipoDocumento", fattura.tipo)
    _sub(doc, "Divisa", "EUR")
    _sub(doc, "Data", fattura.data.isoformat())
    _sub(doc, "Numero", fattura.numero)
    for r in fattura.righe_ritenuta.all():
        nodo = _sub(doc, "DatiRitenuta")
        _sub(nodo, "TipoRitenuta", r.tipo)
        _sub(nodo, "ImportoRitenuta", _d(r.importo))
        _sub(nodo, "AliquotaRitenuta", _d(r.aliquota_ritenuta))
        _sub(nodo, "CausalePagamento", r.causale)
    if fattura.bollo:
        nodo = _sub(doc, "DatiBollo")
        _sub(nodo, "BolloVirtuale", "SI")
        _sub(nodo, "ImportoBollo", _d(fattura.bollo))
    for c in fattura.casse.select_related("aliquota"):
        nodo = _sub(doc, "DatiCassaPrevidenziale")
        _sub(nodo, "TipoCassa", c.tipo)
        _sub(nodo, "AlCassa", _d(c.aliquota_cassa))
        _sub(nodo, "ImportoContributoCassa", _d(c.importo))
        _sub(nodo, "ImponibileCassa", _d(c.imponibile))
        _sub(nodo, "AliquotaIVA", _d(c.aliquota.percentuale))
        if c.soggetta_ritenuta and fattura.ritenute:
            _sub(nodo, "Ritenuta", "SI")
        if c.aliquota.natura:
            _sub(nodo, "Natura", c.aliquota.natura)
    _sub(doc, "ImportoTotaleDocumento", _d(fattura.totale))
    if fattura.causale:
        _sub(doc, "Causale", fattura.causale[:200])
    _riferimenti(generali, fattura)

    beni = _sub(corpo, "DatiBeniServizi")
    for n, r in enumerate(fattura.righe.select_related("aliquota", "prodotto__unita", "unita"), start=1):
        linea = _sub(beni, "DettaglioLinee")
        _sub(linea, "NumeroLinea", n)
        if r.prodotto_id and r.prodotto.codice:
            cod = _sub(linea, "CodiceArticolo")
            _sub(cod, "CodiceTipo", "INTERNO")
            _sub(cod, "CodiceValore", r.prodotto.codice[:35])
        if r.prodotto_id and (del_cliente := codice_cliente(r.prodotto, fattura.cliente)):
            cod = _sub(linea, "CodiceArticolo")
            _sub(cod, "CodiceTipo", "CLIENTE")
            _sub(cod, "CodiceValore", del_cliente.codice[:35])
        _sub(linea, "Descrizione", r.descrizione[:1000] or "—")
        _sub(linea, "Quantita", _d(r.quantita, 3))
        if r.prodotto_id:
            _sub(linea, "UnitaMisura", (r.unita or r.prodotto.unita).simbolo)
        _sub(linea, "PrezzoUnitario", _d(r.prezzo, 4))
        if r.sconto:
            sc = _sub(linea, "ScontoMaggiorazione")
            _sub(sc, "Tipo", "SC")
            _sub(sc, "Percentuale", _d(r.sconto))
        _sub(linea, "PrezzoTotale", _d(r.importo))
        _sub(linea, "AliquotaIVA", _d(r.aliquota.percentuale))
        if fattura.ritenute and r.soggetta_ritenuta:
            _sub(linea, "Ritenuta", "SI")
        if r.aliquota.natura:
            _sub(linea, "Natura", r.aliquota.natura)
        if r.aliquota.natura == "N3.5" and fattura.dichiarazione_intento_id:      # protocollo della dichiarazione d'intento
            d = fattura.dichiarazione_intento
            altri = _sub(linea, "AltriDatiGestionali")
            _sub(altri, "TipoDato", "INTENTO")
            _sub(altri, "RiferimentoTesto", d.protocollo[:60])
            _sub(altri, "RiferimentoData", d.data_protocollo.isoformat())
    for g in fattura.riepilogo_iva():
        al = g["aliquota"]
        riep = _sub(beni, "DatiRiepilogo")
        _sub(riep, "AliquotaIVA", _d(al.percentuale))
        if al.natura:
            _sub(riep, "Natura", al.natura)
        _sub(riep, "ImponibileImporto", _d(g["imponibile"]))
        _sub(riep, "Imposta", _d(g["imposta"]))
        if not al.natura:
            _sub(riep, "EsigibilitaIVA", al.esigibilita)
        if al.natura:
            _sub(riep, "RiferimentoNormativo", (al.riferimento_normativo or al.get_natura_display())[:100])

    scadenze = list(fattura.scadenze.all())
    if scadenze:
        pag = _sub(corpo, "DatiPagamento")
        _sub(pag, "CondizioniPagamento", "TP01" if len(scadenze) > 1 else "TP02")
        for s in scadenze:
            det = _sub(pag, "DettaglioPagamento")
            _sub(det, "ModalitaPagamento", s.modalita)
            _sub(det, "DataScadenzaPagamento", s.data.isoformat())
            _sub(det, "ImportoPagamento", _d(s.importo))
            if dati.iban and s.modalita in ("MP05", "MP19", "MP12"):
                if dati.banca:
                    _sub(det, "IstitutoFinanziario", dati.banca[:80])
                _sub(det, "IBAN", dati.iban.replace(" ", ""))

    ET.indent(radice)
    return nome_file(fattura), ET.tostring(radice, encoding="utf-8", xml_declaration=True)
