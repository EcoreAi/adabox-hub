"""KPI e grafici della Fatturazione per la dashboard."""
import datetime

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from core.dashboard import numero, queryset

from .models import Fattura, Scadenza

MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def _netto(qs):
    """Imponibile delle fatture meno quello delle note di credito."""
    somma = lambda tipo: qs.filter(tipo=tipo).aggregate(t=Sum("imponibile"))["t"] or 0     # noqa: E731
    return somma(Fattura.FATTURA) - somma(Fattura.NOTA_CREDITO)


def kpi(request):
    oggi = timezone.localdate()
    emesse = queryset(request, Fattura).filter(stato=Fattura.EMESSA)
    aperte = queryset(request, Scadenza).filter(pagata=False, fattura__stato=Fattura.EMESSA)
    mesi = []
    primo = oggi.replace(day=1)
    for i in range(5, -1, -1):
        anno, mese = divmod(primo.year * 12 + primo.month - 1 - i, 12)
        mesi.append(datetime.date(anno, mese + 1, 1))
    return {
        "kpi": [{"valore": f"{numero(_netto(emesse.filter(data__year=oggi.year, data__month=oggi.month)))} €",
                 "etichetta": "fatturato nel mese (imponibile)"},
                {"valore": f"{numero(aperte.aggregate(t=Sum('importo'))['t'] or 0)} €", "etichetta": "da incassare"},
                {"valore": f"{numero(aperte.filter(data__lt=oggi).aggregate(t=Sum('importo'))['t'] or 0)} €",
                 "etichetta": "scaduto"},
                {"valore": queryset(request, Fattura).filter(stato=Fattura.BOZZA).count(), "etichetta": "bozze"}],
        "grafici": [{"titolo": "Fatturato negli ultimi 6 mesi (imponibile, €)", "tipo": "barre",
                     "url": reverse("fatturazione:fatture_grafico"),
                     "dati": [(f"{MESI[m.month - 1]} {m.year % 100}",
                               float(_netto(emesse.filter(data__year=m.year, data__month=m.month)))) for m in mesi]}],
    }
