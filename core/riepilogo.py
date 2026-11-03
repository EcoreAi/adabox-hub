"""Il riepilogo giornaliero: che cosa è successo dall'ultimo accesso e che cosa aspetta l'utente oggi.

Ogni modulo lo dichiara nel manifest con la chiave `riepilogo` ("modulo.riepilogo.voci"): una funzione
`voci(request, dal, oggi)` che restituisce una lista di voci fatte con `voce`. `dal` è l'istante dell'accesso
precedente (con fuso), `oggi` la data locale. Le voci parlano solo di ciò che l'utente vede: i conteggi si fanno con
`core.dashboard.queryset`, che applica permessi, azienda e regole di visibilità della ModelView."""
from .generici import url_record

NOVITA, OGGI, ATTENZIONE = "novita", "oggi", "attenzione"
SEZIONI = [(NOVITA, "Dall'ultimo accesso", "Che cosa è successo mentre non c'eri"),
           (OGGI, "Oggi", "Impegni e scadenze di oggi"),
           (ATTENZIONE, "Da fare", "Cose che aspettano te o che vanno tenute d'occhio")]
MAX_DETTAGLI = 5


def voce(sezione, numero, singolare, plurale="", url="", urgente=False, dettagli=None, nota="", testo="", nome=""):
    """Anche con numero zero: il motore la toglie dalla scheda, ma la tiene nel catalogo di ciò che si può silenziare.
    `dettagli`: [(testo, url)] delle prime righe, oppure un queryset da cui ricavarle (letto solo se c'è qualcosa).
    `testo` al posto del conteggio; `nome` è come la voce si chiama nelle impostazioni (di solito basta il plurale)."""
    numero = numero or 0
    if numero and dettagli is not None and not isinstance(dettagli, list):
        dettagli = dettagli_di(dettagli)
    etichetta = singolare if numero == 1 else (plurale or singolare)
    return {"sezione": sezione, "numero": numero, "etichetta": etichetta, "nome": nome or plurale or singolare or testo,
            "testo": testo or f"{numero} {etichetta}", "conteggio": not testo, "url": url or "", "urgente": bool(urgente),
            "dettagli": (dettagli or []) if numero else [], "nota": nota if numero else ""}


def dettagli_di(qs, testo=str, n=MAX_DETTAGLI):
    return [(testo(o), url_record(o) or "") for o in qs[:n]]
