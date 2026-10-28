"""KPI dello SDI per la dashboard."""
from django.urls import reverse

from core.dashboard import queryset

from .models import Trasmissione


def kpi(request):
    qs = queryset(request, Trasmissione)
    lista = reverse("sdi:trasmissioni_lista")
    return {"kpi": [
        {"valore": qs.filter(stato__in=[Trasmissione.PRONTA, Trasmissione.INVIATA]).count(),
         "etichetta": "in attesa dello SDI", "url": f"{lista}?f_stato=inviata"},
        {"valore": qs.filter(stato__in=[Trasmissione.SCARTATA, Trasmissione.ERRORE]).count(),
         "etichetta": "scartate da correggere", "url": f"{lista}?f_stato=scartata"},
        {"valore": qs.filter(stato=Trasmissione.MANCATA_CONSEGNA).count(), "etichetta": "non recapitate"},
    ]}
