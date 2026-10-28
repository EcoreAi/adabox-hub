"""KPI degli Acquisti per la dashboard."""
from django.db.models import Sum
from django.utils import timezone

from core.dashboard import numero, queryset

from .models import OrdineAcquisto


def kpi(request):
    qs = queryset(request, OrdineAcquisto)
    oggi = timezone.localdate()
    aperti = qs.filter(stato__in=[OrdineAcquisto.BOZZA, OrdineAcquisto.INVIATO])
    mese = qs.filter(stato=OrdineAcquisto.CONFERMATO, confermato_il__year=oggi.year, confermato_il__month=oggi.month)
    in_arrivo = qs.filter(stato=OrdineAcquisto.CONFERMATO, consegna_prevista__gte=oggi)
    return {"kpi": [{"valore": f"{numero(mese.aggregate(t=Sum('totale'))['t'] or 0)} €", "etichetta": "ordinato nel mese"},
                    {"valore": aperti.count(), "etichetta": "richieste aperte"},
                    {"valore": in_arrivo.count(), "etichetta": "ordini in arrivo"}]}
