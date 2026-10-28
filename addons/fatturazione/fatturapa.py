"""Fattura elettronica FatturaPA 1.2 (formato FPR12, tra privati): XML e nome del file.

Struttura secondo le specifiche tecniche dell'Agenzia delle Entrate; lo schema XSD ufficiale e l'invio allo SDI
sono del modulo `sdi` (spec fase 5, decisione 9)."""
import xml.etree.ElementTree as ET
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import DatiFiscali, Fattura

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
    if not (cl.partita_iva or cl.codice_fiscale):
        mancano.append("Il cliente non ha né partita IVA né codice fiscale.")
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


def genera(fattura):
    """(nome del file, XML in bytes). ValidationError se mancano dati."""
    problemi = errori(fattura)
    if problemi:
        raise ValidationError(problemi)
    assegna_progressivo(fattura)
    az, cl, dati = fattura.azienda, fattura.cliente, fattura.azienda.dati_fiscali
    radice = ET.Element(f"{{{NS}}}FatturaElettronica", {"versione": "FPR12"})

    testata = _sub(radice, "FatturaElettronicaHeader")
    tx = _sub(testata, "DatiTrasmissione")
    idt = _sub(tx, "IdTrasmittente")
    _sub(idt, "IdPaese", "IT")
    _sub(idt, "IdCodice", az.codice_fiscale or az.partita_iva)
    _sub(tx, "ProgressivoInvio", fattura.progressivo_invio)
    _sub(tx, "FormatoTrasmissione", "FPR12")
    estero = (cl.nazione or "IT") != "IT"
    _sub(tx, "CodiceDestinatario", "XXXXXXX" if estero else (cl.codice_sdi or "0000000").upper())
    if not cl.codice_sdi and cl.pec and not estero:
        _sub(tx, "PECDestinatario", cl.pec)

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

    cessionario = _sub(testata, "CessionarioCommittente")
    anag = _sub(cessionario, "DatiAnagrafici")
    if cl.partita_iva:
        idf = _sub(anag, "IdFiscaleIVA")
        _sub(idf, "IdPaese", cl.nazione or "IT")
        _sub(idf, "IdCodice", cl.partita_iva)
    if cl.codice_fiscale:
        _sub(anag, "CodiceFiscale", cl.codice_fiscale.upper())
    _sub(_sub(anag, "Anagrafica"), "Denominazione", cl.nome[:80])
    _sede(cessionario, cl)

    corpo = _sub(radice, "FatturaElettronicaBody")
    generali = _sub(corpo, "DatiGenerali")
    doc = _sub(generali, "DatiGeneraliDocumento")
    _sub(doc, "TipoDocumento", fattura.tipo)
    _sub(doc, "Divisa", "EUR")
    _sub(doc, "Data", fattura.data.isoformat())
    _sub(doc, "Numero", fattura.numero)
    _sub(doc, "ImportoTotaleDocumento", _d(fattura.totale))
    if fattura.causale:
        _sub(doc, "Causale", fattura.causale[:200])
    if fattura.fattura_origine_id:
        coll = _sub(generali, "DatiFattureCollegate")
        _sub(coll, "IdDocumento", fattura.fattura_origine.numero)
        _sub(coll, "Data", fattura.fattura_origine.data.isoformat())
    elif fattura.ordine_id and fattura.ordine.numero_ordine:
        ord_ = _sub(generali, "DatiOrdineAcquisto")
        _sub(ord_, "IdDocumento", fattura.ordine.riferimento_cliente or fattura.ordine.numero_ordine)
        _sub(ord_, "Data", (fattura.ordine.confermato_il or fattura.ordine.data).isoformat())

    beni = _sub(corpo, "DatiBeniServizi")
    for n, r in enumerate(fattura.righe.select_related("aliquota", "prodotto__unita"), start=1):
        linea = _sub(beni, "DettaglioLinee")
        _sub(linea, "NumeroLinea", n)
        if r.prodotto_id and r.prodotto.codice:
            cod = _sub(linea, "CodiceArticolo")
            _sub(cod, "CodiceTipo", "INTERNO")
            _sub(cod, "CodiceValore", r.prodotto.codice[:35])
        _sub(linea, "Descrizione", r.descrizione[:1000] or "—")
        _sub(linea, "Quantita", _d(r.quantita, 3))
        if r.prodotto_id:
            _sub(linea, "UnitaMisura", r.prodotto.unita.simbolo)
        _sub(linea, "PrezzoUnitario", _d(r.prezzo, 4))
        if r.sconto:
            sc = _sub(linea, "ScontoMaggiorazione")
            _sub(sc, "Tipo", "SC")
            _sub(sc, "Percentuale", _d(r.sconto))
        _sub(linea, "PrezzoTotale", _d(r.importo))
        _sub(linea, "AliquotaIVA", _d(r.aliquota.percentuale))
        if r.aliquota.natura:
            _sub(linea, "Natura", r.aliquota.natura)
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
