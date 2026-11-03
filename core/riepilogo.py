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


def voce(sezione, numero, singolare, plurale="", url="", urgente=False, dettagli=None, nota="", testo=""):
    """None quando il numero è zero, così una funzione restituisce [v for v in (...) if v].
    `dettagli`: [(testo, url)] delle prime righe, oppure un queryset da cui ricavarle. `testo` al posto del conteggio."""
    if not numero:
        return None
    if dettagli is not None and not isinstance(dettagli, list):
        dettagli = dettagli_di(dettagli)
    etichetta = singolare if numero == 1 else (plurale or singolare)
    return {"sezione": sezione, "numero": numero, "etichetta": etichetta, "testo": testo or f"{numero} {etichetta}",
            "conteggio": not testo, "url": url or "", "urgente": bool(urgente), "dettagli": dettagli or [], "nota": nota}


def dettagli_di(qs, testo=str, n=MAX_DETTAGLI):
    return [(testo(o), url_record(o) or "") for o in qs[:n]]
