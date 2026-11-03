"""KPI dei contratti ricorrenti per la dashboard."""
import datetime

from django.urls import reverse
from django.utils import timezone

from core.dashboard import numero, queryset
from fatturazione.dashboard import MESI

from . import operazioni
from .models import Canone


def kpi(request):
    tutti = queryset(request, Canone)
    attivi = operazioni.attivi(tutti)
    entro = timezone.localdate() + datetime.timedelta(days=90)
    return {
        "kpi": [{"valore": f"{numero(operazioni.ricavi_mensili(tutti))} €", "etichetta": "ricavi ricorrenti al mese"},
                {"valore": attivi.count(), "etichetta": "contratti in corso"},
                {"valore": attivi.filter(scadenza__lte=entro).count(), "etichetta": "in scadenza entro 90 giorni"}],
        "grafici": [{"titolo": "Fatture previste dai contratti (imponibile, €)", "tipo": "barre", "url": reverse("ricorrenti:cruscotto"),
                     "dati": [(f"{MESI[m.month - 1]} {m.year % 100}", float(v)) for m, v in operazioni.previsione(attivi, 6)]}],
    }
