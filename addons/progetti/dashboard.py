"""KPI e grafici dei Progetti per la dashboard."""
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset

from .models import Compito, FaseCompito, Progetto


def kpi(request):
    progetti = queryset(request, Progetto).filter(stato=Progetto.ATTIVO)
    compiti = queryset(request, Compito)
    aperti = compiti.filter(fase__chiusa=False)
    per_fase = dict(compiti.values_list("fase").annotate(n=Count("pk")))
    return {
        "kpi": [{"valore": progetti.count(), "etichetta": "progetti attivi"},
                {"valore": aperti.count(), "etichetta": "compiti aperti"},
                {"valore": aperti.filter(scadenza__lt=timezone.localdate()).count(), "etichetta": "in ritardo"},
                {"valore": aperti.filter(assegnatari=request.user).count(), "etichetta": "miei"}],
        "grafici": [{"titolo": "Compiti per fase", "tipo": "barre", "url": reverse("progetti:compiti_kanban"),
                     "dati": [(f.nome, per_fase.get(f.pk, 0)) for f in FaseCompito.objects.all()]}],
    }
