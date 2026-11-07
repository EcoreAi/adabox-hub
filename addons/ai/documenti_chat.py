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
            "Se chiede modifiche si riferisce a questo: leggilo con leggi_documento_chat e cambialo con modifica_documento.")


def scaricamenti(documento):
    """I link per scaricare il documento, da dare all'utente quando chiede il file."""
    from django.urls import reverse
    return {formato: reverse("ai:scarica_documento", args=[documento.pk, formato]) for formato in ("pdf", "docx", "md")}


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
    return {"documento": d.pk, "versione": 1, "scarica": scaricamenti(d),
            "nota": "Il documento è aperto accanto alla chat, dove l'utente lo legge e lo modifica: nella risposta non ricopiarlo, "
                    "di' in breve che cosa contiene. Se chiede un PDF o un file Word dagli il link di «scarica»."}


def leggi_documento_chat(contesto, documento):
    d = _della_chat(contesto, documento)
    ultima = d.versioni.first()
    return {"documento": d.pk, "titolo": d.titolo, "versione": d.versione,
            "ultima_modifica_di": ultima.get_autore_display() if ultima else "", "scarica": scaricamenti(d), "testo": d.testo}


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
                                  "copialo esatto con leggi_documento_chat (aggiungi parole intorno se serve). Nessuna modifica salvata.")
        nuovo = nuovo.replace(cerca, sostituisci, 1)
    if titolo.strip():
        DocumentoChat.objects.filter(pk=d.pk).update(titolo=titolo.strip()[:200])
    d = nuova_versione(d, nuovo, VersioneDocumento.ADA, turno=contesto.turno)
    return {"documento": d.pk, "versione": d.versione, "scarica": scaricamenti(d),
            "nota": "Modifica salvata e visibile accanto alla chat: non ricopiare il documento."}


DOCUMENTO = {"type": "integer", "description": "numero del documento"}
registra(Strumento(
    "scrivi_documento", "Crea un documento lungo (lettera, relazione, procedura, offerta, verbale...) che si apre accanto alla chat: "
                        "l'utente lo legge, lo modifica e lo scarica in PDF, Word o Markdown. Usalo per testi da conservare o rifinire, "
                        "non per le risposte brevi. Testo in Markdown.",
    {"type": "object", "properties": {"titolo": {"type": "string"}, "testo": {"type": "string", "description": "il testo in Markdown"}},
     "required": ["titolo", "testo"]}, scrivi_documento, concorrente=False))
registra(Strumento(
    "leggi_documento_chat", "Legge il testo attuale di un documento scritto in questa chat (non dell'app Documenti): l'utente potrebbe "
                            "averlo modificato.",
    {"type": "object", "properties": {"documento": DOCUMENTO}, "required": ["documento"]}, leggi_documento_chat))
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



STILE_PDF = """@page { size: A4; margin: 22mm 20mm 20mm; @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; color: #86868b; } }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #1d1d1f; }
h1.titolo { font-size: 20pt; margin: 0 0 2mm; } p.sotto { color: #6e6e73; font-size: 9pt; margin: 0 0 8mm; }
h1 { font-size: 16pt; } h2 { font-size: 13.5pt; } h3 { font-size: 12pt; } h4 { font-size: 11pt; }
h1, h2, h3, h4 { margin: 6mm 0 2mm; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 3mm 0; font-size: 9.5pt; page-break-inside: auto; }
th, td { border: 1px solid #d2d2d7; padding: 1.5mm 2.5mm; text-align: left; vertical-align: top; } th { background: #f5f5f7; }
tr { page-break-inside: avoid; } pre { background: #f5f5f7; padding: 3mm; font-size: 8.5pt; white-space: pre-wrap; }
code { font-family: Menlo, Consolas, monospace; } blockquote { border-left: 3px solid #d2d2d7; margin: 3mm 0; padding-left: 4mm; color: #424245; }
a { color: inherit; text-decoration: none; }"""


def in_pdf(documento):
    """Il documento in PDF (A4, numeri di pagina), dallo stesso Markdown che si vede accanto alla chat."""
    from html import escape

    from django.utils import timezone

    from core import report

    from .markdown import rendi
    HTML = report.weasyprint().HTML                       # ReportNonDisponibile senza Pango
    sotto = " · ".join(x for x in (str(documento.azienda or ""), f"{timezone.localtime(documento.aggiornato):%d/%m/%Y}"
                                   if getattr(documento, "aggiornato", None) else "") if x)
    pagina = (f"<html><head><meta charset='utf-8'><title>{escape(documento.titolo)}</title><style>{STILE_PDF}</style></head>"
              f"<body><h1 class='titolo'>{escape(documento.titolo)}</h1>{f'<p class=sotto>{escape(sotto)}</p>' if sotto else ''}"
              f"{rendi(documento.testo)}</body></html>")
    return HTML(string=pagina).write_pdf()
