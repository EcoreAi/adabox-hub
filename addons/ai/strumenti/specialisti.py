"""Strumenti degli specialisti locali: previsione di una serie dai dati del gestionale e classificazione di un testo.
Visibili solo se il loro servizio è configurato nelle impostazioni."""
from .. import specialisti        # può essere ancora a metà caricamento: i suoi nomi si usano solo nelle funzioni
from .registro import ErroreStrumento, Strumento, registra
from .viste import FILTRI, TESTO, VISTA

MAX_ORIZZONTE = 24                # = specialisti.MAX_ORIZZONTE (qui serve già all'import, per lo schema)


def previsione(contesto, vista, data, misura="count", per="mese", orizzonte=3, filtri=None, testo="", titolo=""):
    from .. import artifact
    from ..models import Artifact
    try:
        orizzonte = max(1, min(int(orizzonte), MAX_ORIZZONTE))
    except (TypeError, ValueError):
        raise ErroreStrumento("«orizzonte» è un numero intero di periodi.")
    if contesto.conversazione is None:
        raise ErroreStrumento("Le previsioni si mostrano solo in una chat.")
    spec = {"tipo": Artifact.GRAFICO, "grafico": "previsione", "vista": vista, "data": data,
            "misura": misura or "count", "per": per, "orizzonte": orizzonte, "filtri": filtri or {}, "testo": testo or ""}
    dati = specialisti.calcola_previsione(spec, contesto)
    a = artifact._crea(contesto, Artifact.GRAFICO, titolo or f"Previsione {vista}: {misura or 'count'} per {per}",
                       spec, dati)
    return {"artifact": a.pk, "titolo": a.titolo, "ultimi_periodi": dati["storico"][-6:],
            "previsione": [{"periodo": p, "basso_10": b, "mediana": m, "alto_90": a_} for p, b, m, a_ in dati["futuro"]],
            "periodi_di_storia": len(dati["storico"]), "modello": dati["modello"],
            "nota": "Numeri calcolati dal modello di previsione sulla storia del gestionale; il periodo in corso non è "
                    "nella storia perché incompleto. Riporta la mediana con l'intervallo 10-90 % e ricorda che è una "
                    "stima. Il grafico è sotto la risposta."}


def classifica(contesto, testo, domanda, tipo="si_no", opzioni=None):
    if not (testo or "").strip() or not (domanda or "").strip():
        raise ErroreStrumento("Servono il testo da valutare e la domanda.")
    risposta = specialisti.decidi(testo, domanda, tipo, opzioni)
    return {**risposta, "nota": "Probabilità calcolate dal decisore locale (nessun dato al cloud). Con "
                                "backend embed_sim (senza esempi addestrati) sono indicative: usale come indizio."}


registra(Strumento(
    "previsione", "Prevede i prossimi periodi di una misura del gestionale (es. fatturato o numero di ordini per mese) "
                  "con un modello di previsione locale: storia dai dati reali, previsione con mediana e fascia 10-90 %, "
                  "grafico sotto la risposta.",
    {"type": "object", "properties": {
        "vista": VISTA, "data": {"type": "string", "description": "campo data della serie, es. data"},
        "misura": {"type": "string", "description": "count (default) oppure sum:campo, es. sum:totale"},
        "per": {"type": "string", "enum": ["mese", "settimana", "giorno"], "description": "periodo (default mese)"},
        "orizzonte": {"type": "integer", "description": f"periodi da prevedere (1-{MAX_ORIZZONTE}, default 3)"},
        "filtri": FILTRI, "testo": TESTO, "titolo": {"type": "string"}},
     "required": ["vista", "data"]}, previsione, disponibile=lambda: bool(specialisti.url("url_forecast"))))
registra(Strumento(
    "classifica", "Valuta un testo con il decisore locale e restituisce probabilità: sì/no, scelta tra opzioni o "
                  "punteggio su livelli (es. urgenza di un ticket, categoria di una richiesta).",
    {"type": "object", "properties": {
        "testo": {"type": "string", "description": "il testo da valutare"},
        "domanda": {"type": "string", "description": "es. Il ticket è urgente?"},
        "tipo": {"type": "string", "enum": ["si_no", "scelta", "punteggio"]},
        "opzioni": {"description": "per scelta {nome: descrizione}; per punteggio la lista dei livelli dal più basso"}},
     "required": ["testo", "domanda"]}, classifica, disponibile=lambda: bool(specialisti.url("url_decider"))))
