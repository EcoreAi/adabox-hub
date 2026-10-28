"""KPI del Magazzino per la dashboard."""
from django.urls import reverse

from .models import Consegna, Ricevimento
from .pagine import situazione
from core.dashboard import queryset


def kpi(request):
    _, sotto = situazione(request, solo_sotto_scorta=True)
    return {"kpi": [{"valore": len(sotto), "etichetta": "prodotti sotto scorta"},
                    {"valore": queryset(request, Consegna).filter(stato=Consegna.BOZZA).count(), "etichetta": "consegne da spedire"},
                    {"valore": queryset(request, Ricevimento).filter(stato=Ricevimento.BOZZA).count(),
                     "etichetta": "ricevimenti attesi"}],
            "grafici": [{"titolo": "Prodotti sotto scorta", "tipo": "barre",
                         "url": reverse("magazzino:giacenze") + "?sotto_scorta=1",
                         "dati": [(str(r["prodotto"].nome)[:18], float(r["prodotto"].scorta_minima - r["totale"]))
                                  for r in sotto[:10]]}] if sotto else []}
