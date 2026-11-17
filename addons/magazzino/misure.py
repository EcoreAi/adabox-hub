"""Misura aziendale del Magazzino (core.misure): i prodotti sotto scorta, calcolati come nella pagina delle giacenze."""
from django.urls import reverse

from core.misure import Misura, registra


def _url_prodotto(prodotto):
    from core.viste import registry
    vista = registry.per_modello(type(prodotto))
    try:
        return vista.url("dettaglio", pk=prodotto.pk) if vista else ""
    except Exception:
        return ""


def sotto_scorta(request, di=""):
    from .pagine import situazione
    _, righe = situazione(request, solo_sotto_scorta=True)
    return {"valore": len(righe), "url": reverse("magazzino:giacenze") + "?sotto_scorta=1",
            "righe": [{"etichetta": str(r["prodotto"].nome), "url": _url_prodotto(r["prodotto"]),
                       "valore": float(max(r["prodotto"].scorta_minima - r["previsto"], 0))} for r in righe]}


registra(Misura(
    nome="magazzino.sotto_scorta", etichetta="Prodotti sotto scorta", unita="",
    definizione="prodotti attivi la cui giacenza prevista (giacenza + in arrivo − impegnato) è sotto la scorta minima "
                "o sotto il punto di riordino di un magazzino; il valore di ogni prodotto è la quantità che manca",
    sinonimi=("scorte basse", "da riordinare"), funzione=sotto_scorta,
    permesso="magazzino.view_movimento"))           # senza i movimenti ogni giacenza sembrerebbe zero
