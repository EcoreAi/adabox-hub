"""KPI e grafici delle Vendite per la dashboard."""
import datetime

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from core.dashboard import numero, queryset

from .models import OrdineVendita

MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def kpi(request):
    qs = queryset(request, OrdineVendita)
    oggi = timezone.localdate()
    aperti = qs.filter(stato__in=[OrdineVendita.BOZZA, OrdineVendita.INVIATO])
    confermati = qs.filter(stato=OrdineVendita.CONFERMATO)
    del_mese = confermati.filter(confermato_il__year=oggi.year, confermato_il__month=oggi.month)
    mesi = []
    primo = oggi.replace(day=1)
    for i in range(5, -1, -1):
        anno, mese = divmod(primo.year * 12 + primo.month - 1 - i, 12)
        mesi.append(datetime.date(anno, mese + 1, 1))
    return {
        "kpi": [{"valore": f"{numero(del_mese.aggregate(t=Sum('totale'))['t'] or 0)} €", "etichetta": "ordinato nel mese"},
                {"valore": aperti.count(), "etichetta": "preventivi aperti"},
                {"valore": f"{numero(aperti.aggregate(t=Sum('totale'))['t'] or 0)} €", "etichetta": "in preventivo"},
                {"valore": del_mese.count(), "etichetta": "ordini nel mese"}],
        "grafici": [{"titolo": "Ordinato negli ultimi 6 mesi (€)", "tipo": "barre", "url": reverse("vendite:ordini_grafico"),
                     "dati": [(f"{MESI[m.month - 1]} {m.year % 100}",
                               float(confermati.filter(confermato_il__year=m.year, confermato_il__month=m.month)
                                     .aggregate(t=Sum("totale"))["t"] or 0)) for m in mesi]}],
    }
