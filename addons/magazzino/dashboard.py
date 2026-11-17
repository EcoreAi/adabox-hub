"""KPI del Magazzino per la dashboard."""
from core import misure
from core.dashboard import queryset

from .models import Consegna, Ricevimento


def kpi(request):
    sotto = misure.calcola("magazzino.sotto_scorta", request)       # la stessa misura dell'assistente
    return {"kpi": [{"valore": sotto["valore"], "etichetta": "prodotti sotto scorta"},
                    {"valore": queryset(request, Consegna).filter(stato__in=Consegna.APERTI).count(), "etichetta": "consegne da spedire"},
                    {"valore": queryset(request, Ricevimento).filter(stato=Ricevimento.BOZZA).count(),
                     "etichetta": "ricevimenti attesi"}],
            "grafici": [{"titolo": "Prodotti sotto scorta", "tipo": "barre", "url": sotto["url"],
                         "dati": [(g["gruppo"][:18], g["valore"]) for g in sotto["gruppi"][:10]]}] if sotto["gruppi"] else []}
