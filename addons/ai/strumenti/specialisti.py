"""Lo strumento di classificazione di un testo con il decisore locale: visibile solo se il suo servizio è configurato.
La previsione di una serie vive nel modulo Previsioni (`previsioni/ai.py`)."""
from .. import specialisti        # può essere ancora a metà caricamento: i suoi nomi si usano solo nelle funzioni
from .registro import ErroreStrumento, Strumento, registra


def classifica(contesto, testo, domanda, tipo="si_no", opzioni=None):
    if not (testo or "").strip() or not (domanda or "").strip():
        raise ErroreStrumento("Servono il testo da valutare e la domanda.")
    risposta = specialisti.decidi(testo, domanda, tipo, opzioni)
    return {**risposta, "nota": "Probabilità calcolate dal decisore locale (nessun dato al cloud). Con "
                                "backend embed_sim (senza esempi addestrati) sono indicative: usale come indizio."}


registra(Strumento(
    "classifica", "Valuta un testo con il decisore locale e restituisce probabilità: sì/no, scelta tra opzioni o "
                  "punteggio su livelli (es. urgenza di un ticket, categoria di una richiesta).",
    {"type": "object", "properties": {
        "testo": {"type": "string", "description": "il testo da valutare"},
        "domanda": {"type": "string", "description": "es. Il ticket è urgente?"},
        "tipo": {"type": "string", "enum": ["si_no", "scelta", "punteggio"]},
        "opzioni": {"description": "per scelta {nome: descrizione}; per punteggio la lista dei livelli dal più basso"}},
     "required": ["testo", "domanda"]}, classifica, disponibile=lambda: bool(specialisti.url("url_decider"))))
