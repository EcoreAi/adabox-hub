"""Fatture dei fornitori: estrazione dal .p7m, lettura dell'XML FatturaPA, registrazione e pagamenti."""
import base64
import datetime
import subprocess
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from lxml import etree

from contatti.models import Contatto
from core.models import Azienda

from .models import FatturaPassiva, NotificaSdi, RiepilogoPassiva, RigaPassiva, ScadenzaPassiva
from .segnali import fattura_ricevuta


class FatturaNonValida(ValueError):
    pass


def estrai_p7m(contenuto):
    """L'XML dentro una busta CAdES (.p7m), DER o base64. La firma l'ha già verificata lo SDI."""
    for dati in (contenuto, _base64(contenuto)):
        if not dati:
            continue
        esito = subprocess.run(["openssl", "cms", "-verify", "-noverify", "-inform", "DER", "-binary"],
                               input=dati, capture_output=True, timeout=30)
        if esito.returncode == 0 and esito.stdout.lstrip().startswith(b"<"):
            return esito.stdout
    raise FatturaNonValida("File .p7m non leggibile.")


def _base64(contenuto):
    try:
        return base64.b64decode(contenuto, validate=False)
    except (ValueError, TypeError):
        return None


def e_fattura(contenuto):
    try:
        radice = etree.fromstring(contenuto, _parser())
    except etree.XMLSyntaxError:
        return False
    return etree.QName(radice).localname == "FatturaElettronica"


def _parser():
    return etree.XMLParser(no_network=True, resolve_entities=False, huge_tree=False)


def _t(nodo, percorso):
    """Testo del primo elemento al percorso relativo (nomi senza namespace, separati da /)."""
    if nodo is None:
        return ""
    xpath = "./" + "/".join(f"*[local-name()='{p}']" for p in percorso.split("/"))
    trovati = nodo.xpath(xpath)
    return (trovati[0].text or "").strip() if trovati else ""


def _n(nodo, percorso, default="0"):
    try:
        return Decimal(_t(nodo, percorso) or default)
    except InvalidOperation:
        return Decimal(default)


def _d(testo):
    try:
        return datetime.date.fromisoformat(testo[:10]) if testo else None
    except ValueError:
        return None


def _uno(nodo, percorso):
    xpath = "./" + "/".join(f"*[local-name()='{p}']" for p in percorso.split("/"))
    trovati = nodo.xpath(xpath)
    return trovati[0] if trovati else None


def _tutti(nodo, nome):
    return nodo.xpath(f"./*[local-name()='{nome}']")


def ritenute_di(gen):
    """I dati delle ritenute (DatiRitenuta, anche più d'uno) e della cassa previdenziale di DatiGeneraliDocumento."""
    ritenute = [r for r in (_tutti(gen, "DatiRitenuta") if gen is not None else [])
                if _t(r, "TipoRitenuta") in ("RT01", "RT02", "")]          # RT03-RT06 sono contributi (INPS, ENASARCO…), non IRPEF
    importo = sum((_n(r, "ImportoRitenuta") for r in ritenute), Decimal(0))
    base = Decimal(0)
    for r in ritenute:
        aliquota = _n(r, "AliquotaRitenuta")
        if aliquota:
            base += (_n(r, "ImportoRitenuta") * 100 / aliquota).quantize(Decimal("0.01"))
    principale = max(ritenute, key=lambda r: _n(r, "ImportoRitenuta"), default=None)
    cassa = sum((_n(c, "ImportoContributoCassa") for c in (_tutti(gen, "DatiCassaPrevidenziale") if gen is not None else [])), Decimal(0))
    return {"ritenuta": importo, "base_ritenuta": base, "aliquota_ritenuta": _n(principale, "AliquotaRitenuta") if principale is not None else Decimal(0),
            "tipo_ritenuta": _t(principale, "TipoRitenuta")[:4], "causale_ritenuta": _t(principale, "CausalePagamento")[:2],
            "contributo_cassa": cassa}


CAMPI_RITENUTA = ("ritenuta", "base_ritenuta", "aliquota_ritenuta", "tipo_ritenuta", "causale_ritenuta", "contributo_cassa")


def leggi(contenuto):
    """{cedente, cessionario, documenti: [...]} dall'XML (un file può contenere più fatture: un "lotto")."""
    try:
        radice = etree.fromstring(contenuto, _parser())
    except etree.XMLSyntaxError as e:
        raise FatturaNonValida(f"XML non leggibile: {e}")
    if etree.QName(radice).localname != "FatturaElettronica":
        raise FatturaNonValida("Non è una fattura elettronica.")
    testata = _uno(radice, "FatturaElettronicaHeader")
    ced = _uno(testata, "CedentePrestatore")
    ces = _uno(testata, "CessionarioCommittente")

    def soggetto(nodo):
        anag = _uno(nodo, "DatiAnagrafici")
        nome = _t(anag, "Anagrafica/Denominazione") or " ".join(
            p for p in (_t(anag, "Anagrafica/Nome"), _t(anag, "Anagrafica/Cognome")) if p)
        return {"paese": _t(anag, "IdFiscaleIVA/IdPaese"), "partita_iva": _t(anag, "IdFiscaleIVA/IdCodice"),
                "codice_fiscale": _t(anag, "CodiceFiscale"), "nome": nome,
                "indirizzo": " ".join(p for p in (_t(nodo, "Sede/Indirizzo"), _t(nodo, "Sede/NumeroCivico")) if p),
                "cap": _t(nodo, "Sede/CAP"), "citta": _t(nodo, "Sede/Comune"), "provincia": _t(nodo, "Sede/Provincia"),
                "nazione": _t(nodo, "Sede/Nazione") or "IT"}

    documenti = []
    for corpo in _tutti(radice, "FatturaElettronicaBody"):
        gen = _uno(corpo, "DatiGenerali/DatiGeneraliDocumento")
        beni = _uno(corpo, "DatiBeniServizi")
        righe = [{"numero_linea": int(_t(r, "NumeroLinea") or 0), "descrizione": _t(r, "Descrizione"),
                  "quantita": _n(r, "Quantita", "") if _t(r, "Quantita") else None, "unita": _t(r, "UnitaMisura"),
                  "prezzo": _n(r, "PrezzoUnitario"), "importo": _n(r, "PrezzoTotale"),
                  "aliquota": _n(r, "AliquotaIVA"), "natura": _t(r, "Natura")}
                 for r in _tutti(beni, "DettaglioLinee")]
        riepilogo = [{"aliquota": _n(r, "AliquotaIVA"), "natura": _t(r, "Natura"),
                      "imponibile": _n(r, "ImponibileImporto"), "imposta": _n(r, "Imposta"),
                      "esigibilita": _t(r, "EsigibilitaIVA")} for r in _tutti(beni, "DatiRiepilogo")]
        imponibile = sum((r["imponibile"] for r in riepilogo), Decimal(0))
        imposta = sum((r["imposta"] for r in riepilogo), Decimal(0))
        scadenze = [{"data": _d(_t(p, "DataScadenzaPagamento")), "importo": _n(p, "ImportoPagamento"),
                     "modalita": _t(p, "ModalitaPagamento"), "iban": _t(p, "IBAN")}
                    for pag in _tutti(corpo, "DatiPagamento") for p in _tutti(pag, "DettaglioPagamento")]
        totale = _n(gen, "ImportoTotaleDocumento", "") if _t(gen, "ImportoTotaleDocumento") else imponibile + imposta
        generali = _uno(corpo, "DatiGenerali")
        riferimenti = {"ordini": [_t(o, "IdDocumento") for o in _tutti(generali, "DatiOrdineAcquisto")],
                       "ddt": [_t(d, "NumeroDDT") for d in _tutti(generali, "DatiDDT")]}
        documenti.append({
            **ritenute_di(gen),
            "riferimenti": riferimenti, "tipo": _t(gen, "TipoDocumento") or "TD01", "numero": _t(gen, "Numero"), "data": _d(_t(gen, "Data")),
            "causale": "\n".join(c.text or "" for c in _tutti(gen, "Causale")),
            "imponibile": imponibile, "imposta": imposta, "totale": totale,
            "righe": righe, "riepilogo": riepilogo, "scadenze": scadenze})
    if not documenti or not all(d["numero"] and d["data"] for d in documenti):
        raise FatturaNonValida("Numero o data della fattura mancanti.")
    return {"cedente": soggetto(ced), "cessionario": soggetto(ces), "documenti": documenti}


def azienda_di(cessionario, predefinita=None):
    """L'azienda destinataria, dalla partita IVA (o dal codice fiscale) del cessionario."""
    for campo in ("partita_iva", "codice_fiscale"):
        valore = cessionario.get(campo)
        if valore:
            trovata = Azienda.objects.filter(**{campo: valore}).first()
            if trovata:
                return trovata
    return predefinita


def fornitore_di(azienda, cedente):
    piva = cedente["partita_iva"]
    qs = Contatto.objects.filter(azienda=azienda)
    trovato = (piva and qs.filter(partita_iva=piva).first()) or (
        cedente["codice_fiscale"] and qs.filter(codice_fiscale=cedente["codice_fiscale"]).first())
    if trovato:
        if not trovato.fornitore:
            trovato.fornitore = True
            trovato.save(update_fields=["fornitore"])
        return trovato
    note = ""
    return Contatto.objects.create(
        azienda=azienda, nome=cedente["nome"][:200] or "Fornitore", fornitore=True, partita_iva=piva[:28],
        codice_fiscale=cedente["codice_fiscale"][:16], indirizzo=cedente["indirizzo"][:200], cap=cedente["cap"][:10],
        citta=cedente["citta"][:100], provincia=cedente["provincia"][:2], nazione=cedente["nazione"][:2], note=note)


@transaction.atomic
def importa(nome_file, contenuto, azienda=None):
    """[(fattura, nuova)] da un file ricevuto (XML o .p7m). FatturaNonValida se non è leggibile o non è nostra."""
    originale = contenuto
    xml = estrai_p7m(contenuto) if nome_file.lower().endswith(".p7m") else contenuto
    dati = leggi(xml)
    destinataria = azienda_di(dati["cessionario"], azienda)
    if destinataria is None:
        raise FatturaNonValida("Il destinatario della fattura non è un'azienda di questa installazione.")
    fornitore = fornitore_di(destinataria, dati["cedente"])
    mt = NotificaSdi.objects.filter(tipo="MT", file_fattura=nome_file).first()
    risultati = []
    for doc in dati["documenti"]:
        esistente = FatturaPassiva.objects.filter(azienda=destinataria, fornitore=fornitore, numero=doc["numero"],
                                                  data=doc["data"]).first()
        if esistente:
            risultati.append((esistente, False))
            continue
        f = FatturaPassiva.objects.create(
            azienda=destinataria, fornitore=fornitore, tipo_documento=doc["tipo"][:4], numero=doc["numero"][:20],
            data=doc["data"], causale=doc["causale"], imponibile=doc["imponibile"], imposta=doc["imposta"],
            totale=doc["totale"], nome_file=nome_file[:80], originale=ContentFile(originale, name=nome_file),
            identificativo_sdi=mt.identificativo_sdi if mt else "", ritenuta_letta=True, **{c: doc[c] for c in CAMPI_RITENUTA})
        RigaPassiva.objects.bulk_create(RigaPassiva(fattura=f, **r) for r in doc["righe"])
        RiepilogoPassiva.objects.bulk_create(RiepilogoPassiva(fattura=f, **r) for r in doc["riepilogo"])
        scadenze = doc["scadenze"] or [{"data": doc["data"], "importo": doc["totale"], "modalita": "", "iban": ""}]
        ScadenzaPassiva.objects.bulk_create(ScadenzaPassiva(fattura=f, **s) for s in scadenze)
        fattura_ricevuta.send(sender=FatturaPassiva, fattura=f, riferimenti=doc["riferimenti"])
        risultati.append((f, True))
    return risultati


def collega_metadati(notifica):
    """Un file di metadati (MT) porta l'identificativo SDI della fattura ricevuta con lo stesso messaggio."""
    if notifica.tipo == "MT" and notifica.file_fattura:
        FatturaPassiva.objects.filter(nome_file=notifica.file_fattura, identificativo_sdi="").update(
            identificativo_sdi=notifica.identificativo_sdi)


def registra(fattura):
    fattura.stato, fattura.registrata_il = FatturaPassiva.REGISTRATA, timezone.localdate()
    fattura.save(update_fields=["stato", "registrata_il"])


def aggiorna_scadenza(scadenza):
    """Da chiamare dopo ogni pagamento: importo pagato, scadenza chiusa o riaperta, fattura pagata o no."""
    pagamenti = list(scadenza.pagamenti.all())
    scadenza.pagato = sum((p.importo for p in pagamenti), Decimal(0))
    scadenza.pagata = scadenza.pagato >= scadenza.importo
    scadenza.pagata_il = max((p.data for p in pagamenti), default=None) if scadenza.pagata else None
    scadenza.save(update_fields=["pagato", "pagata", "pagata_il"])
    fattura = scadenza.fattura
    fattura.pagata = not fattura.scadenze.filter(pagata=False).exists()
    fattura.save(update_fields=["pagata"])


@transaction.atomic
def paga(scadenza, data=None, importo=None, tipo="pagamento", metodo="bonifico", riferimento="", utente=None):
    """Un pagamento (o un abbuono) sulla scadenza del fornitore: senza importo, tutto il residuo. Restituisce il pagamento."""
    from .models import PagamentoPassivo
    scadenza = ScadenzaPassiva.objects.select_for_update().select_related("fattura").get(pk=scadenza.pk)
    importo = scadenza.residuo if importo is None else Decimal(importo).quantize(Decimal("0.01"))
    if importo <= 0:
        raise ValidationError("L'importo deve essere positivo.")
    if importo > scadenza.residuo:
        raise ValidationError(f"Restano da pagare {scadenza.residuo} €: non puoi registrarne {importo}.")
    pagamento = PagamentoPassivo.objects.create(scadenza=scadenza, tipo=tipo, data=data or timezone.localdate(), importo=importo,
                                                metodo=metodo, riferimento=riferimento[:120], utente=utente)
    aggiorna_scadenza(scadenza)
    return pagamento


@transaction.atomic
def annulla_pagamento(pagamento):
    scadenza = pagamento.scadenza
    pagamento.delete()
    aggiorna_scadenza(scadenza)


@transaction.atomic
def riapri(scadenza, riferimento=None):
    """Toglie i pagamenti della scadenza (solo quelli con quel riferimento, se indicato): torna da pagare."""
    pagamenti = scadenza.pagamenti.all()
    if riferimento is not None:
        pagamenti = pagamenti.filter(riferimento=riferimento)
    pagamenti.delete()
    aggiorna_scadenza(scadenza)
    fattura = scadenza.fattura
    fattura.pagata = not fattura.scadenze.filter(pagata=False).exists()
    fattura.save(update_fields=["pagata"])
