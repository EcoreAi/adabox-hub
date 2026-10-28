"""Lettura dei file di notifica dello SDI e aggiornamento delle trasmissioni."""
import re

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from lxml import etree

from core import chatter

from .models import NotificaSdi, Trasmissione

NOME = re.compile(r"^(?P<emittente>[A-Z]{2}[A-Za-z0-9]{1,28})_(?P<progressivo>[A-Za-z0-9]{1,5})"
                  r"_(?P<tipo>RC|NS|MC|NE|DT|AT|EC|SE|MT)_(?P<n>\d{3})\.xml$")
RADICI = {"RicevutaConsegna": "RC", "NotificaScarto": "NS", "NotificaMancataConsegna": "MC",
          "NotificaEsito": "NE", "NotificaDecorrenzaTermini": "DT", "AttestazioneTrasmissioneFattura": "AT",
          "NotificaEsitoCommittente": "EC", "ScartoEsitoCommittente": "SE", "FileMetadati": "MT"}


class FileNonRiconosciuto(ValueError):
    pass


def _testo(radice, nome):
    trovati = radice.xpath(f"//*[local-name()='{nome}']")
    return (trovati[0].text or "").strip() if trovati else ""


def _figlio(elemento, nome):
    trovati = elemento.xpath(f"./*[local-name()='{nome}']")
    return (trovati[0].text or "").strip() if trovati else ""


def leggi(contenuto, nome_file=""):
    """{tipo, identificativo_sdi, file_fattura, data_ricezione, errori, esito, ...} da un file di notifica."""
    try:
        radice = etree.fromstring(contenuto, etree.XMLParser(no_network=True, resolve_entities=False))
    except etree.XMLSyntaxError as e:
        raise FileNonRiconosciuto(f"«{nome_file}»: XML non leggibile ({e})")
    tipo = RADICI.get(etree.QName(radice).localname)
    if tipo is None and (m := NOME.match(nome_file)):
        tipo = m["tipo"]
    if tipo is None:
        raise FileNonRiconosciuto(f"«{nome_file}»: non è una notifica dello SDI")
    errori = [{campo: _figlio(e, nome) for campo, nome in (("codice", "Codice"), ("descrizione", "Descrizione"),
                                                         ("suggerimento", "Suggerimento"))}
              for e in radice.xpath("//*[local-name()='Errore']")]
    return {"tipo": tipo, "identificativo_sdi": _testo(radice, "IdentificativoSdI"),
            "file_fattura": _testo(radice, "NomeFile"), "data_ricezione": _testo(radice, "DataOraRicezione"),
            "data_consegna": _testo(radice, "DataOraConsegna"), "esito": _testo(radice, "Esito"),
            "descrizione": _testo(radice, "Descrizione") if not errori else "",
            "message_id": _testo(radice, "MessageId"), "pec_sdi": _testo(radice, "PECDestinatario"),
            "errori": errori}


ESITI = {"RC": Trasmissione.CONSEGNATA, "NS": Trasmissione.SCARTATA, "MC": Trasmissione.MANCATA_CONSEGNA,
         "DT": Trasmissione.DECORSA, "AT": Trasmissione.MANCATA_CONSEGNA}
MESSAGGI = {
    Trasmissione.CONSEGNATA: "Lo SDI ha consegnato la fattura al cliente.",
    Trasmissione.SCARTATA: "Lo SDI ha scartato la fattura: correggi e reinvia (il numero resta valido).",
    Trasmissione.MANCATA_CONSEGNA: "Lo SDI non ha potuto recapitare la fattura: è valida ed è nel cassetto "
                                   "fiscale del cliente; mandagliene una copia di cortesia.",
    Trasmissione.ACCETTATA: "La pubblica amministrazione ha accettato la fattura.",
    Trasmissione.RIFIUTATA: "La pubblica amministrazione ha rifiutato la fattura: emetti una nota di credito.",
    Trasmissione.DECORSA: "Decorsi i termini: la fattura vale come accettata.",
}


@transaction.atomic
def registra(contenuto, nome_file, azienda=None):
    """Salva la notifica (una volta sola per nome di file) e aggiorna la trasmissione a cui si riferisce.
    Restituisce (notifica, nuova)."""
    esistente = NotificaSdi.objects.filter(nome_file=nome_file).first()
    if esistente is not None:
        return esistente, False
    dati = leggi(contenuto, nome_file)
    trasmissione = None
    if dati["file_fattura"]:
        trasmissione = Trasmissione.objects.filter(nome_file=dati["file_fattura"]).order_by("-pk").first()
    if trasmissione is None and dati["identificativo_sdi"]:
        trasmissione = Trasmissione.objects.filter(identificativo_sdi=dati["identificativo_sdi"]).first()
    if trasmissione is None and (m := NOME.match(nome_file)):
        trasmissione = Trasmissione.objects.filter(
            nome_file=f"{m['emittente']}_{m['progressivo']}.xml").order_by("-pk").first()
    notifica = NotificaSdi.objects.create(
        trasmissione=trasmissione, azienda=trasmissione.azienda if trasmissione else azienda, tipo=dati["tipo"],
        nome_file=nome_file, file=ContentFile(contenuto, name=nome_file), dati=dati,
        identificativo_sdi=dati["identificativo_sdi"], file_fattura=dati["file_fattura"])
    if trasmissione is not None:
        aggiorna(trasmissione, notifica)
    return notifica, True


def aggiorna(trasmissione, notifica):
    dati = notifica.dati
    stato = ESITI.get(notifica.tipo)
    if notifica.tipo == "NE":
        stato = Trasmissione.ACCETTATA if dati.get("esito") == "EC01" else Trasmissione.RIFIUTATA
    if dati.get("identificativo_sdi") and not trasmissione.identificativo_sdi:
        trasmissione.identificativo_sdi = dati["identificativo_sdi"]
    if stato is None:
        trasmissione.save(update_fields=["identificativo_sdi"])
        return
    trasmissione.stato, trasmissione.esito_il = stato, timezone.now()
    trasmissione.errori = dati.get("errori", []) if stato == Trasmissione.SCARTATA else []
    trasmissione.save(update_fields=["stato", "esito_il", "errori", "identificativo_sdi"])
    testo = MESSAGGI.get(stato, "")
    if trasmissione.errori:
        testo += "\n" + "\n".join(f"{e['codice']}: {e['descrizione']}" for e in trasmissione.errori)
    chatter.scrivi(trasmissione.fattura, None, f"{notifica.get_tipo_display()} ({trasmissione.nome_file}). {testo}",
                   tipo="nota")
