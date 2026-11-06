"""Comunicazione delle liquidazioni periodiche IVA (LIPE), fornitura IVP18, dalle liquidazioni del trimestre.

Struttura e controlli seguono le specifiche tecniche dell'Agenzia delle Entrate (Comunicazione IVA Trimestrale,
aggiornamento 2024). Qui si fanno i controlli bloccanti che dipendono dai dati; prima dell'invio il file va passato
nel software di controllo gratuito dell'Agenzia (o lo controlla lo studio che lo trasmette)."""
import re
from decimal import Decimal
from xml.etree import ElementTree as ET

from django.utils import timezone

from contatti.validatori import codice_fiscale_valido

from core import parametri

from . import calcolo
from .models import Liquidazione

NS = "urn:www.agenziaentrate.gov.it:specificheTecniche:sco:ivp"
ZERO = Decimal(0)
SCADENZE = {1: "31 maggio", 2: "30 settembre", 3: "30 novembre", 4: "fine febbraio dell'anno dopo (o nella dichiarazione annuale)"}


def importo(valore):
    return f"{Decimal(valore):.2f}".replace(".", ",")


def partita_iva_valida(piva):
    if not re.fullmatch(r"\d{11}", piva or ""):
        return False
    somma = 0
    for i, c in enumerate(piva[:10]):
        n = int(c)
        if i % 2:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        somma += n
    return (10 - somma % 10) % 10 == int(piva[10])


def _cf_valido(cf):
    return partita_iva_valida(cf) if len(cf or "") == 11 else codice_fiscale_valido(cf or "")


def _el(padre, nome, testo=None):
    e = ET.SubElement(padre, f"{{{NS}}}{nome}")
    if testo is not None:
        e.text = str(testo)
    return e


def risultati(azienda, anno, trimestre):
    periodicita = calcolo.periodicita_di(azienda)
    periodi = calcolo.mesi(Liquidazione.TRIMESTRALE, trimestre) if periodicita == Liquidazione.MENSILE else (trimestre,)
    cache = {}
    return periodicita, [calcolo.liquida(azienda, anno, periodicita, p, cache) for p in periodi]


def controlli(azienda, anno, trimestre, periodicita, voci):
    """(errori, avvisi): con errori il file non si genera."""
    errori, avvisi = [], []
    piva = (azienda.partita_iva or "").upper().removeprefix("IT")
    cf = (azienda.codice_fiscale or piva).upper()
    if not partita_iva_valida(piva):
        errori.append("La partita IVA dell'azienda manca o non è valida (Impostazioni → Azienda).")
    if not _cf_valido(cf):
        errori.append("Il codice fiscale dell'azienda non è valido.")
    dichiarante = (parametri.leggi("iva.cf_dichiarante", azienda) or "").strip().upper()
    if len(cf) == 11 and not dichiarante:
        errori.append("Per una società serve il codice fiscale di chi firma la comunicazione (impostazioni del modulo IVA).")
    if dichiarante and not codice_fiscale_valido(dichiarante):
        errori.append("Il codice fiscale di chi firma non è valido.")
    intermediario = (parametri.leggi("iva.cf_intermediario", azienda) or "").strip().upper()
    if intermediario and not _cf_valido(intermediario):
        errori.append("Il codice fiscale dell'intermediario non è valido.")
    if anno < timezone.localdate().year - 1:
        avvisi.append("Le specifiche ammettono solo l'anno in corso e quello prima: per anni più vecchi serve l'integrativa nella dichiarazione.")
    for r in voci:
        if r.debito_precedente > calcolo.soglia():
            errori.append(f"{r.nome}: il debito del periodo prima supera la soglia di {calcolo.soglia()} €.")
        if r.acconto and r.acconto < Decimal("103.29"):
            errori.append(f"{r.nome}: l'acconto deve essere almeno 103,29 €.")
        if r.liquidazione is None or not r.liquidazione.chiusa:
            avvisi.append(f"{r.nome}: la liquidazione non è chiusa, i numeri possono ancora cambiare.")
        elif calcolo.cambiati(r):
            avvisi.append(f"{r.nome}: dopo la chiusura i registri sono cambiati. Riapri e richiudi la liquidazione se va corretta.")
    if periodicita == Liquidazione.TRIMESTRALE and trimestre == 4:
        avvisi.append("Il quarto trimestre si può comunicare anche nella dichiarazione IVA annuale.")
    return errori, avvisi


def genera(azienda, anno, trimestre):
    """(nome_file, xml in bytes, errori, avvisi). Con errori non c'è file."""
    periodicita, voci = risultati(azienda, anno, trimestre)
    errori, avvisi = controlli(azienda, anno, trimestre, periodicita, voci)
    if errori:
        return None, None, errori, avvisi
    piva = azienda.partita_iva.upper().removeprefix("IT")
    cf = (azienda.codice_fiscale or piva).upper()
    ET.register_namespace("iv", NS)
    radice = ET.Element(f"{{{NS}}}Fornitura")
    intestazione = _el(radice, "Intestazione")
    _el(intestazione, "CodiceFornitura", "IVP18")
    comunicazione = _el(radice, "Comunicazione")
    comunicazione.set("identificativo", "00001")
    fronte = _el(comunicazione, "Frontespizio")
    _el(fronte, "CodiceFiscale", cf)
    _el(fronte, "AnnoImposta", anno)
    _el(fronte, "PartitaIVA", piva)
    dichiarante = (parametri.leggi("iva.cf_dichiarante", azienda) or "").strip().upper()
    if dichiarante:
        _el(fronte, "CFDichiarante", dichiarante)
        _el(fronte, "CodiceCaricaDichiarante", parametri.leggi("iva.carica_dichiarante", azienda) or 1)
    _el(fronte, "FirmaDichiarazione", 1)
    intermediario = (parametri.leggi("iva.cf_intermediario", azienda) or "").strip().upper()
    if intermediario:
        _el(fronte, "CFIntermediario", intermediario)
        _el(fronte, "ImpegnoPresentazione", 1)
        _el(fronte, "DataImpegno", timezone.localdate().strftime("%d%m%Y"))
        _el(fronte, "FirmaIntermediario", 1)
    _el(fronte, "IdentificativoProdSoftware", "ADABOX HUB")
    contabili = _el(comunicazione, "DatiContabili")
    for numero, r in enumerate(voci, start=1):
        modulo = _el(contabili, "Modulo")
        _el(modulo, "NumeroModulo", numero)
        _el(modulo, "Mese" if periodicita == Liquidazione.MENSILE else "Trimestre", r.periodo)
        for nome, valore in (("TotaleOperazioniAttive", r.attive), ("TotaleOperazioniPassive", r.passive),
                             ("IvaEsigibile", r.esigibile), ("IvaDetratta", r.detratta)):
            _el(modulo, nome, importo(valore))
        if r.iva_credito:
            _el(modulo, "IvaCredito", importo(r.iva_credito))
        else:
            _el(modulo, "IvaDovuta", importo(r.iva_dovuta))
        for nome, valore in (("DebitoPrecedente", r.debito_precedente), ("CreditoPeriodoPrecedente", r.credito_precedente),
                             ("CreditoAnnoPrecedente", r.credito_anno_precedente), ("VersamentiAuto", r.versamenti_auto),
                             ("CreditiImposta", r.crediti_imposta), ("InteressiDovuti", r.interessi)):
            if valore:
                _el(modulo, nome, importo(valore))
        if r.acconto:
            _el(modulo, "Metodo", r.liquidazione.metodo_acconto or 1)
            _el(modulo, "Acconto", importo(r.acconto))
        if r.a_credito:
            _el(modulo, "ImportoACredito", importo(r.a_credito))
        else:
            _el(modulo, "ImportoDaVersare", importo(r.da_versare))
    ET.indent(radice)
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(radice, encoding="utf-8", xml_declaration=False)
    return f"LIPE_{piva}_{anno}_T{trimestre}.xml", xml, errori, avvisi
