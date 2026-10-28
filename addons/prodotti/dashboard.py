"""KPI dei Prodotti per la dashboard."""
from core.dashboard import queryset

from .models import Prodotto


def kpi(request):
    attivi = queryset(request, Prodotto).filter(attivo=True)
    return {"kpi": [{"valore": attivi.count(), "etichetta": "prodotti attivi"},
                    {"valore": attivi.filter(tipo=Prodotto.BENE).count(), "etichetta": "beni"},
                    {"valore": attivi.filter(tipo=Prodotto.SERVIZIO).count(), "etichetta": "servizi"}]}
