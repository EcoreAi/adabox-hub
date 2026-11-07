"""File SEPA ISO 20022: bonifici (pain.001) e addebiti diretti (pain.008), validati con lo schema XSD ufficiale."""
from collections import OrderedDict
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils import timezone
from lxml import etree

from .models import ConfigConto
from .testo import sepa

SCHEMI = Path(__file__).parent / "schemi"
VERSIONI = {ConfigConto.ISO_2019: {"bonifici": "pain.001.001.09", "sdd": "pain.008.001.08"},
            ConfigConto.ISO_2009: {"bonifici": "pain.001.001.03", "sdd": "pain.008.001.02"}}


@lru_cache
def schema(nome):
    return etree.XMLSchema(etree.parse(str(SCHEMI / f"{nome}.xsd")))


class Scrittore:
    def __init__(self, messaggio):
        self.messaggio = messaggio
        self.ns = f"urn:iso:std:iso:20022:tech:xsd:{messaggio}"
        self.recente = messaggio in ("pain.001.001.09", "pain.008.001.08")

    def el(self, padre, nome, testo=None, **attributi):
        e = etree.SubElement(padre, f"{{{self.ns}}}{nome}", **attributi)
        if testo is not None:
            e.text = str(testo)
        return e

    def percorso(self, padre, percorso, testo):
        nodo = padre
        for nome in percorso.split("/"):
            nodo = self.el(nodo, nome)
        nodo.text = str(testo)
        return nodo

    def agente(self, padre, nome, bic):
        istituto = self.el(self.el(padre, nome), "FinInstnId")
        if bic:
            self.el(istituto, "BICFI" if self.recente else "BIC", bic)
        else:
            self.percorso(istituto, "Othr/Id", "NOTPROVIDED")


def _importo(valore):
    return f"{Decimal(valore):.2f}"


def _testata(w, radice, distinta, voci):
    testata = w.el(radice, "GrpHdr")
    w.el(testata, "MsgId", distinta.identificativo)
    w.el(testata, "CreDtTm", timezone.localtime().replace(microsecond=0, tzinfo=None).isoformat())
    w.el(testata, "NbOfTxs", len(voci))
    w.el(testata, "CtrlSum", _importo(sum(v.importo for v in voci)))
    w.el(w.el(testata, "InitgPty"), "Nm", sepa(distinta.azienda.nome, 70))


def bonifici(distinta, voci, versione):
    w = Scrittore(VERSIONI[versione]["bonifici"])
    documento = etree.Element(f"{{{w.ns}}}Document", nsmap={None: w.ns})
    radice = w.el(documento, "CstmrCdtTrfInitn")
    _testata(w, radice, distinta, voci)
    blocco = w.el(radice, "PmtInf")
    w.el(blocco, "PmtInfId", f"{distinta.identificativo}-1"[:35])
    w.el(blocco, "PmtMtd", "TRF")
    w.el(blocco, "BtchBookg", "true")
    w.el(blocco, "NbOfTxs", len(voci))
    w.el(blocco, "CtrlSum", _importo(sum(v.importo for v in voci)))
    w.percorso(w.el(blocco, "PmtTpInf"), "SvcLvl/Cd", "SEPA")
    if w.recente:
        w.percorso(blocco, "ReqdExctnDt/Dt", distinta.data.isoformat())
    else:
        w.el(blocco, "ReqdExctnDt", distinta.data.isoformat())
    w.el(w.el(blocco, "Dbtr"), "Nm", sepa(distinta.azienda.nome, 70))
    w.percorso(blocco, "DbtrAcct/Id/IBAN", distinta.conto.iban)
    w.agente(blocco, "DbtrAgt", distinta.conto.bic)
    w.el(blocco, "ChrgBr", "SLEV")
    for v in voci:
        tx = w.el(blocco, "CdtTrfTxInf")
        w.el(w.el(tx, "PmtId"), "EndToEndId", f"D{distinta.pk}V{v.pk}")
        w.el(w.el(tx, "Amt"), "InstdAmt", _importo(v.importo), Ccy="EUR")
        w.el(w.el(tx, "Cdtr"), "Nm", sepa(v.nome, 70))
        w.percorso(tx, "CdtrAcct/Id/IBAN", v.iban)
        w.el(w.el(tx, "RmtInf"), "Ustrd", sepa(v.causale, 140))
    return documento


def addebiti(distinta, voci, versione, id_creditore):
    w = Scrittore(VERSIONI[versione]["sdd"])
    documento = etree.Element(f"{{{w.ns}}}Document", nsmap={None: w.ns})
    radice = w.el(documento, "CstmrDrctDbtInitn")
    _testata(w, radice, distinta, voci)
    gruppi = OrderedDict()
    for v in voci:
        gruppi.setdefault(v.mandato.schema, []).append(v)
    for n, (schema_sdd, gruppo) in enumerate(gruppi.items(), start=1):
        blocco = w.el(radice, "PmtInf")
        w.el(blocco, "PmtInfId", f"{distinta.identificativo}-{n}"[:35])
        w.el(blocco, "PmtMtd", "DD")
        w.el(blocco, "BtchBookg", "true")
        w.el(blocco, "NbOfTxs", len(gruppo))
        w.el(blocco, "CtrlSum", _importo(sum(v.importo for v in gruppo)))
        tipo = w.el(blocco, "PmtTpInf")
        w.percorso(tipo, "SvcLvl/Cd", "SEPA")
        w.percorso(tipo, "LclInstrm/Cd", schema_sdd)
        w.el(tipo, "SeqTp", "RCUR")
        w.el(blocco, "ReqdColltnDt", distinta.data.isoformat())
        w.el(w.el(blocco, "Cdtr"), "Nm", sepa(distinta.azienda.nome, 70))
        w.percorso(blocco, "CdtrAcct/Id/IBAN", distinta.conto.iban)
        w.agente(blocco, "CdtrAgt", distinta.conto.bic)
        w.el(blocco, "ChrgBr", "SLEV")
        altro = w.percorso(blocco, "CdtrSchmeId/Id/PrvtId/Othr/Id", id_creditore).getparent()
        w.percorso(altro, "SchmeNm/Prtry", "SEPA")
        for v in gruppo:
            tx = w.el(blocco, "DrctDbtTxInf")
            w.el(w.el(tx, "PmtId"), "EndToEndId", f"D{distinta.pk}V{v.pk}")
            w.el(tx, "InstdAmt", _importo(v.importo), Ccy="EUR")
            mandato = w.el(w.el(tx, "DrctDbtTx"), "MndtRltdInf")
            w.el(mandato, "MndtId", v.mandato.riferimento)
            w.el(mandato, "DtOfSgntr", v.mandato.data_firma.isoformat())
            w.agente(tx, "DbtrAgt", v.mandato.bic)
            w.el(w.el(tx, "Dbtr"), "Nm", sepa(v.nome, 70))
            w.percorso(tx, "DbtrAcct/Id/IBAN", v.iban)
            w.el(w.el(tx, "RmtInf"), "Ustrd", sepa(v.causale, 140))
    return documento


def serializza(documento, messaggio):
    """Bytes del file, dopo la validazione con lo schema: un file che la banca scarterebbe non esce."""
    valido = schema(messaggio)
    if not valido.validate(documento):
        errori = "; ".join(f"riga {e.line}: {e.message}" for e in list(valido.error_log)[:3])
        raise ValidationError(f"Il file non rispetta lo schema {messaggio}: {errori}")
    return etree.tostring(documento, xml_declaration=True, encoding="UTF-8", pretty_print=True)
