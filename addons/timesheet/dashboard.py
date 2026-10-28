"""KPI e grafici del Timesheet per la dashboard."""
import datetime

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from core.dashboard import numero, queryset

from .models import RigaOre


def kpi(request):
    mie = queryset(request, RigaOre).filter(utente=request.user)
    oggi = timezone.localdate()
    lunedi = oggi - datetime.timedelta(days=oggi.weekday())
    settimane = [lunedi - datetime.timedelta(weeks=i) for i in range(5, -1, -1)]

    def ore(qs):
        return qs.aggregate(t=Sum("ore"))["t"] or 0
    return {
        "kpi": [{"valore": numero(ore(mie.filter(data__gte=lunedi))), "etichetta": "mie ore questa settimana"},
                {"valore": numero(ore(mie.filter(data=oggi))), "etichetta": "oggi"},
                {"valore": numero(ore(mie.filter(data__year=oggi.year, data__month=oggi.month))), "etichetta": "nel mese"}],
        "grafici": [{"titolo": "Le mie ore nelle ultime 6 settimane", "tipo": "linee", "url": reverse("timesheet:settimana"),
                     "dati": [(f"{s.day}/{s.month}", float(ore(mie.filter(data__gte=s, data__lt=s + datetime.timedelta(days=7)))))
                              for s in settimane]}],
    }
