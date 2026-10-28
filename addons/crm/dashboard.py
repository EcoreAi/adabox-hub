"""KPI e grafici del CRM per la dashboard."""
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils import timezone

from core.dashboard import numero, queryset

from .models import FaseCrm, Opportunita


def kpi(request):
    qs = queryset(request, Opportunita)
    aperte = qs.filter(stato=Opportunita.APERTA)
    oggi = timezone.localdate()
    vinte_mese = qs.filter(stato=Opportunita.VINTA, chiusa_il__year=oggi.year, chiusa_il__month=oggi.month)
    pipeline = aperte.aggregate(t=Sum("valore_atteso"))["t"] or 0
    per_fase = dict(aperte.values_list("fase").annotate(t=Sum("valore_atteso")))
    return {
        "kpi": [{"valore": aperte.count(), "etichetta": "opportunità aperte"},
                {"valore": f"{numero(pipeline)} €", "etichetta": "in pipeline"},
                {"valore": vinte_mese.count(), "etichetta": "vinte questo mese"},
                {"valore": aperte.filter(commerciale=request.user).count(), "etichetta": "mie"}],
        "grafici": [{"titolo": "Pipeline per fase (€)", "tipo": "barre", "url": reverse("crm:opportunita_kanban"),
                     "dati": [(f.nome, float(per_fase.get(f.pk) or 0)) for f in FaseCrm.objects.filter(vinta=False)]}],
    }
