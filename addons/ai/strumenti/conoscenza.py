"""Strumenti della conoscenza: ricerca nei testi (record, note, documenti) con citazioni, lettura di documenti e
fogli Excel/CSV. Sempre con i permessi di chi chiede: un risultato si vede solo se la sua ModelView lo mostra."""
import csv
import io

from django.conf import settings
from django.contrib.contenttypes.models import ContentType

from . import richiesta
from .registro import ErroreStrumento, Strumento, registra

LUNGHEZZA_ESTRATTO = 700
PAGINA_DOCUMENTO = 12000
MAX_RIGHE_FOGLIO = 200


def _visibilita(contesto):
    """visibile(frammento) con una cache per record: ModelView del record, permesso di vista, queryset dell'utente."""
    from core.viste import registry

    from core.registry.modules import disattivati

    from ..conoscenza import ESCLUSI
    request = richiesta.per(contesto)
    spenti = ESCLUSI | disattivati()
    cache = {}

    def visibile(frammento):
        chiave = (frammento.content_type_id, frammento.object_id)
        if chiave not in cache:
            modello = ContentType.objects.get_for_id(frammento.content_type_id).model_class()
            vista = registry.per_modello(modello) if modello else None
            cache[chiave] = None
            if vista is not None and vista.modulo not in spenti:
                vista = vista.personalizzata(request)
                if vista.has_view_permission(request) and vista.get_queryset(request).filter(
                        pk=frammento.object_id).exists():
                    cache[chiave] = vista
        return cache[chiave] is not None
    visibile.cache = cache
    return visibile


def cerca_conoscenza(contesto, domanda, fonti=None, app="", limite=8):
    from .. import conoscenza
    from ..models import Frammento
    if not (domanda or "").strip():
        raise ErroreStrumento("Indica la domanda o le parole da cercare.")
    ammesse = dict(Frammento.FONTI)
    fonti = [f for f in (fonti or []) if f in ammesse] or None
    ambito = getattr(contesto.conversazione, "ambito", "") or ""
    try:
        limite = max(1, min(int(limite), 15))
    except (TypeError, ValueError):
        limite = 8
    visibile = _visibilita(contesto)
    trovati = conoscenza.cerca(domanda, contesto.utente, contesto.azienda, fonti, ambito or app, limite, visibile)
    if not trovati:
        return {"risultati": [], "nota": "Nessun testo pertinente tra quelli che l'utente può vedere. Dillo, senza "
                                         "inventare; se serve prova con altre parole o con cerca_record."}
    risultati = []
    for n, (f, punteggio) in enumerate(trovati, start=1):
        vista = visibile.cache[(f.content_type_id, f.object_id)]
        try:
            url = vista.url("dettaglio", pk=f.object_id)
        except Exception:
            url = ""
        estratto = f.testo if len(f.testo) <= LUNGHEZZA_ESTRATTO else f.testo[:LUNGHEZZA_ESTRATTO] + "…"
        risultati.append({"n": n, "fonte": f.get_fonte_display(), "titolo": f.titolo, "url": url,
                          "vista": f"{vista.modulo}.{vista.slug}", "id": f.object_id, "estratto": estratto,
                          "pertinenza": punteggio})
    semantica = bool(conoscenza.url_servizio())
    return {"risultati": risultati, "ricerca": "semantica e per parole chiave" if semantica else "per parole chiave",
            "istruzioni": "Rispondi solo con quello che dicono questi estratti e cita ogni informazione con il "
                          "numero della fonte come link Markdown, es. [1](url). Se gli estratti non bastano, dillo."}


def _documento(contesto, id):
    if "documenti" not in settings.ADDONS_ATTIVI:
        raise ErroreStrumento("L'app Documenti non è installata.")
    from .viste import oggetto, vista_per
    vista = vista_per(contesto, "documenti.documenti")
    return vista, oggetto(vista, richiesta.per(contesto), id)


def _dati(documento):
    file = documento.contenuto
    if not file:
        raise ErroreStrumento("Il documento non ha un file.")
    with file.open("rb") as f:
        return f.read(20 * 1024 * 1024)


def leggi_documento(contesto, id, pagina=1):
    from ..conoscenza import testo_da_file
    vista, d = _documento(contesto, id)
    testo = testo_da_file(d.nome, _dati(d))
    if not testo.strip():
        raise ErroreStrumento(f"Dal file «{d.nome}» non si ricava testo (tipo non supportato o scansione senza testo).")
    try:
        pagina = max(1, int(pagina))
    except (TypeError, ValueError):
        pagina = 1
    pagine = (len(testo) + PAGINA_DOCUMENTO - 1) // PAGINA_DOCUMENTO
    inizio = (pagina - 1) * PAGINA_DOCUMENTO
    return {"documento": d.nome, "url": vista.url("dettaglio", pk=d.pk), "pagina": pagina, "pagine": pagine,
            "testo": testo[inizio:inizio + PAGINA_DOCUMENTO]}


def leggi_foglio(contesto, id, foglio="", testo="", limite=50):
    from ..conoscenza import fogli
    vista, d = _documento(contesto, id)
    dati = _dati(d)
    nome = d.nome.lower()
    if nome.endswith((".csv", ".tsv")):
        contenuto = dati.decode("utf-8-sig", errors="replace")
        separatore = "\t" if nome.endswith(".tsv") else (";" if contenuto.count(";") > contenuto.count(",") else ",")
        tabelle = [(d.nome, [r for r in csv.reader(io.StringIO(contenuto), delimiter=separatore) if any(r)])]
    elif nome.endswith((".xlsx", ".xlsm")):
        tabelle = fogli(dati)
    else:
        raise ErroreStrumento("leggi_foglio vale per file Excel (.xlsx) e CSV.")
    nomi = [n for n, _ in tabelle]
    scelto = next((t for t in tabelle if t[0] == foglio), None) if foglio else tabelle[0] if tabelle else None
    if scelto is None:
        raise ErroreStrumento(f"Foglio «{foglio}» inesistente. Fogli: {', '.join(nomi)}.")
    righe = scelto[1]
    if not righe:
        return {"documento": d.nome, "fogli": nomi, "foglio": scelto[0], "righe": []}
    intestazione, corpo = [str(c) for c in righe[0]], righe[1:]
    if testo:
        cercato = testo.lower()
        corpo = [r for r in corpo if any(cercato in str(c).lower() for c in r)]
    try:
        limite = max(1, min(int(limite), MAX_RIGHE_FOGLIO))
    except (TypeError, ValueError):
        limite = 50
    return {"documento": d.nome, "url": vista.url("dettaglio", pk=d.pk), "fogli": nomi, "foglio": scelto[0],
            "colonne": intestazione, "righe_totali": len(corpo),
            "righe": [[c if isinstance(c, (int, float)) else str(c) for c in r] for r in corpo[:limite]]}


registra(Strumento(
    "cerca_conoscenza", "Cerca nei testi dell'azienda che l'utente può vedere: contenuto dei documenti (PDF, Word, "
                        "Excel, testo), note e messaggi del chatter, campi di testo dei record. Per domande su cosa dice "
                        "un contratto, una nota, una descrizione. Restituisce estratti numerati con il link da citare.",
    {"type": "object", "properties": {
        "domanda": {"type": "string", "description": "la domanda o le parole da cercare"},
        "fonti": {"type": "array", "items": {"type": "string", "enum": ["documento", "nota", "record"]},
                  "description": "solo queste fonti (default tutte)"},
        "app": {"type": "string", "description": "solo i testi di quest'app (slug)"},
        "limite": {"type": "integer", "description": "risultati (max 15, default 8)"}},
     "required": ["domanda"]}, cerca_conoscenza))
registra(Strumento(
    "leggi_documento", "Il testo di un documento dell'app Documenti, a pagine di circa 12.000 caratteri: per leggere "
                       "per intero un documento trovato con cerca_conoscenza.",
    {"type": "object", "properties": {"id": {"type": "integer", "description": "id del documento"},
                                      "pagina": {"type": "integer", "description": "da 1"}},
     "required": ["id"]}, leggi_documento, app="documenti"))
registra(Strumento(
    "leggi_foglio", "Le righe di un file Excel o CSV dell'app Documenti (prima riga = intestazione), con un filtro di "
                    "testo facoltativo. Per i numeri su tante righe, riassumi o chiedi un grafico dalle viste.",
    {"type": "object", "properties": {"id": {"type": "integer", "description": "id del documento"},
                                      "foglio": {"type": "string", "description": "nome del foglio (default il primo)"},
                                      "testo": {"type": "string", "description": "solo le righe che lo contengono"},
                                      "limite": {"type": "integer", "description": f"righe (max {MAX_RIGHE_FOGLIO})"}},
     "required": ["id"]}, leggi_foglio, app="documenti"))
