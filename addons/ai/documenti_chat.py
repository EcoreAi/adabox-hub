"""I documenti scritti con Ada accanto alla chat (come un canvas). Ada li crea e li modifica con i suoi strumenti,
l'utente li modifica nell'editor; ogni modifica è una versione che si può ripristinare. Non toccano i dati del
gestionale, quindi non chiedono conferma: nel peggiore dei casi si torna alla versione di prima."""
import io
import re

from django.db import transaction

from .models import DocumentoChat, VersioneDocumento
from .strumenti import ErroreStrumento, Strumento, registra

MASSIMO_TESTO = 100_000
MASSIME_VERSIONI = 50


class Conflitto(Exception):
    """Il documento è cambiato dopo che l'editor l'ha aperto."""


def crea(conversazione, utente, azienda, titolo, testo, turno=None):
    with transaction.atomic():
        d = DocumentoChat.objects.create(conversazione=conversazione, utente=utente, azienda=azienda,
                                         titolo=(titolo or "Documento").strip()[:200], testo=testo)
        VersioneDocumento.objects.create(documento=d, numero=1, testo=testo, autore=VersioneDocumento.ADA, turno=turno)
    return d


def nuova_versione(documento, testo, autore, versione_vista=None, turno=None):
    """Salva il testo come nuova versione. Con `versione_vista`: rifiuta se nel frattempo qualcuno l'ha cambiato."""
    if len(testo) > MASSIMO_TESTO:
        raise ErroreStrumento(f"Il documento supera {MASSIMO_TESTO} caratteri.")
    with transaction.atomic():
        d = DocumentoChat.objects.select_for_update().get(pk=documento.pk)
        if versione_vista is not None and d.versione != versione_vista:
            raise Conflitto()
        if d.testo == testo:
            return d
        d.testo, d.versione = testo, d.versione + 1
        d.save(update_fields=["testo", "versione", "aggiornato"])
        VersioneDocumento.objects.create(documento=d, numero=d.versione, testo=testo, autore=autore, turno=turno)
        vecchie = list(d.versioni.values_list("pk", flat=True)[MASSIME_VERSIONI:])
        VersioneDocumento.objects.filter(pk__in=vecchie).delete()
    return d


def nota(documento):
    """Per Ada, quando l'utente scrive con il documento aperto accanto alla chat."""
    if documento is None:
        return ""
    return (f"Accanto alla chat l'utente ha aperto il documento n. {documento.pk} «{documento.titolo}» (versione {documento.versione}). "
            "Se chiede modifiche si riferisce a questo: leggilo con leggi_documento e cambialo con modifica_documento.")


# ---------- strumenti di Ada ----------

def _della_chat(contesto, documento):
    if contesto.conversazione is None:
        raise ErroreStrumento("I documenti si scrivono solo in una chat.")
    try:
        return DocumentoChat.objects.get(pk=int(documento), conversazione=contesto.conversazione, utente=contesto.utente)
    except (TypeError, ValueError, DocumentoChat.DoesNotExist):
        raise ErroreStrumento(f"Documento n. {documento} non trovato in questa chat.") from None


def scrivi_documento(contesto, titolo, testo):
    if contesto.conversazione is None:
        raise ErroreStrumento("I documenti si scrivono solo in una chat.")
    if len(testo) > MASSIMO_TESTO:
        raise ErroreStrumento(f"Il documento supera {MASSIMO_TESTO} caratteri.")
    d = crea(contesto.conversazione, contesto.utente, contesto.azienda, titolo, testo, contesto.turno)
    return {"documento": d.pk, "versione": 1,
            "nota": "Il documento è aperto accanto alla chat, dove l'utente lo legge e lo modifica: nella risposta non ricopiarlo, "
                    "di' in breve che cosa contiene."}


def leggi_documento(contesto, documento):
    d = _della_chat(contesto, documento)
    ultima = d.versioni.first()
    return {"documento": d.pk, "titolo": d.titolo, "versione": d.versione,
            "ultima_modifica_di": ultima.get_autore_display() if ultima else "", "testo": d.testo}


def modifica_documento(contesto, documento, modifiche=None, testo=None, titolo=""):
    d = _della_chat(contesto, documento)
    if testo is None and not modifiche:
        raise ErroreStrumento("Indica le «modifiche» (cerca e sostituisci) oppure il nuovo «testo» intero.")
    nuovo = d.testo if testo is None else testo
    for i, m in enumerate(modifiche or [], 1):
        cerca, sostituisci = (m or {}).get("cerca", ""), (m or {}).get("sostituisci", "")
        volte = nuovo.count(cerca) if cerca else 0
        if volte != 1:
            raise ErroreStrumento(f"Modifica {i}: il testo da cercare compare {volte} volte; deve comparire una volta sola, "
                                  "copialo esatto con leggi_documento (aggiungi parole intorno se serve). Nessuna modifica salvata.")
        nuovo = nuovo.replace(cerca, sostituisci, 1)
    if titolo.strip():
        DocumentoChat.objects.filter(pk=d.pk).update(titolo=titolo.strip()[:200])
    d = nuova_versione(d, nuovo, VersioneDocumento.ADA, turno=contesto.turno)
    return {"documento": d.pk, "versione": d.versione, "nota": "Modifica salvata e visibile accanto alla chat: non ricopiare il documento."}


DOCUMENTO = {"type": "integer", "description": "numero del documento"}
registra(Strumento(
    "scrivi_documento", "Crea un documento lungo (lettera, relazione, procedura, offerta, verbale...) che si apre accanto alla chat: "
                        "l'utente lo legge, lo modifica e lo scarica in Word o Markdown. Usalo per testi da conservare o rifinire, "
                        "non per le risposte brevi. Testo in Markdown.",
    {"type": "object", "properties": {"titolo": {"type": "string"}, "testo": {"type": "string", "description": "il testo in Markdown"}},
     "required": ["titolo", "testo"]}, scrivi_documento, concorrente=False))
registra(Strumento(
    "leggi_documento", "Legge il testo attuale di un documento della chat: l'utente potrebbe averlo modificato.",
    {"type": "object", "properties": {"documento": DOCUMENTO}, "required": ["documento"]}, leggi_documento))
registra(Strumento(
    "modifica_documento", "Modifica un documento della chat. Per cambiare una parte usa «modifiche»: ogni «cerca» deve essere copiato "
                          "esatto dal testo attuale e comparire una volta sola. Per riscriverlo tutto usa «testo». Ogni modifica è "
                          "una versione che l'utente può annullare.",
    {"type": "object", "properties": {
        "documento": DOCUMENTO,
        "modifiche": {"type": "array", "items": {"type": "object", "properties": {"cerca": {"type": "string"}, "sostituisci": {"type": "string"}},
                                                  "required": ["cerca", "sostituisci"]}},
        "testo": {"type": "string", "description": "il nuovo testo intero, al posto delle modifiche"},
        "titolo": {"type": "string", "description": "nuovo titolo, se cambia"}},
     "required": ["documento"]}, modifica_documento, concorrente=False))


# ---------- esportazione ----------

_GRASSETTO = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")


def _righe_inline(paragrafo, testo):
    for pezzo in _GRASSETTO.split(testo):
        if pezzo.startswith("**") and pezzo.endswith("**") and len(pezzo) > 4:
            paragrafo.add_run(pezzo[2:-2]).bold = True
        elif pezzo.startswith("*") and pezzo.endswith("*") and len(pezzo) > 2:
            paragrafo.add_run(pezzo[1:-1]).italic = True
        elif pezzo:
            paragrafo.add_run(pezzo)


def in_word(documento):
    """Il documento in .docx: titoli, elenchi, grassetto e corsivo; il resto come testo."""
    from docx import Document
    doc = Document()
    doc.core_properties.title = documento.titolo
    doc.add_heading(documento.titolo, level=0)
    for riga in documento.testo.splitlines():
        s = riga.strip()
        if not s:
            continue
        if m := re.match(r"(#{1,4})\s+(.*)", s):
            doc.add_heading(m.group(2), level=len(m.group(1)))
        elif m := re.match(r"[-*+]\s+(.*)", s):
            _righe_inline(doc.add_paragraph(style="List Bullet"), m.group(1))
        elif m := re.match(r"\d+[.)]\s+(.*)", s):
            _righe_inline(doc.add_paragraph(style="List Number"), m.group(1))
        else:
            _righe_inline(doc.add_paragraph(), s)
    uscita = io.BytesIO()
    doc.save(uscita)
    return uscita.getvalue()

