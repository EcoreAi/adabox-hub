"""KPI e grafici del Calendario per la dashboard."""
import datetime

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset

from .models import Evento

GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def kpi(request):
    qs = queryset(request, Evento)
    oggi = timezone.localdate()
    tra_30 = oggi + datetime.timedelta(days=30)
    prossimi = qs.filter(inizio__date__gte=oggi, inizio__date__lte=tra_30)
    settimana = [oggi + datetime.timedelta(days=i) for i in range(7)]
    per_giorno = dict(qs.filter(inizio__date__in=settimana).annotate(g=TruncDate("inizio"))
                      .values_list("g").annotate(n=Count("pk")))
    return {
        "kpi": [{"valore": prossimi.count(), "etichetta": "appuntamenti nei prossimi 30 giorni"},
                {"valore": qs.filter(inizio__date=oggi).count(), "etichetta": "oggi"},
                {"valore": qs.filter(inizio__date=oggi + datetime.timedelta(days=1)).count(), "etichetta": "domani"}],
        "grafici": [{"titolo": "Appuntamenti dei prossimi 7 giorni", "tipo": "barre",
                     "url": reverse("calendario:eventi_calendario"),
                     "dati": [(f"{GIORNI[g.weekday()]} {g.day}", per_giorno.get(g, 0)) for g in settimana]}],
    }
