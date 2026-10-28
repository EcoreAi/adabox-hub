"""KPI di Contatti per la dashboard."""
from core.dashboard import queryset

from .models import Contatto


def kpi(request):
    qs = queryset(request, Contatto).filter(attivo=True)
    return {"kpi": [{"valore": qs.count(), "etichetta": "contatti"},
                    {"valore": qs.filter(cliente=True).count(), "etichetta": "clienti"},
                    {"valore": qs.filter(fornitore=True).count(), "etichetta": "fornitori"},
                    {"valore": qs.filter(tipo=Contatto.AZIENDA).count(), "etichetta": "aziende"}]}
