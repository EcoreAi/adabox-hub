"""KPI e grafici di To-Do per la dashboard."""
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset

from .models import Attivita


def kpi(request):
    qs = queryset(request, Attivita)
    aperte = qs.filter(stato__in=[Attivita.APERTA, Attivita.IN_CORSO])
    oggi = timezone.localdate()
    lista = reverse("todo:attivita_lista")
    per_stato = dict(qs.values_list("stato").annotate(n=Count("pk")))
    return {
        "kpi": [{"valore": aperte.count(), "etichetta": "da fare"},
                {"valore": aperte.filter(scadenza=oggi).count(), "etichetta": "oggi"},
                {"valore": aperte.filter(scadenza__lt=oggi).count(), "etichetta": "scadute"}],
        "grafici": [{"titolo": "Attività per stato", "tipo": "torta", "url": lista,
                     "dati": [(etichetta, per_stato.get(valore, 0)) for valore, etichetta in Attivita.STATI]}],
    }
