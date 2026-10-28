"""KPI e grafici dell'Helpdesk per la dashboard."""
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset

from .models import Ticket


def kpi(request):
    aperti = queryset(request, Ticket).filter(fase__chiusa=False)
    per_priorita = dict(aperti.values_list("priorita").annotate(n=Count("pk")))
    return {
        "kpi": [{"valore": aperti.count(), "etichetta": "ticket aperti"},
                {"valore": aperti.filter(scadenza_sla__lt=timezone.now()).count(), "etichetta": "SLA scaduti"},
                {"valore": aperti.filter(assegnatario=request.user).count(), "etichetta": "assegnati a me"},
                {"valore": aperti.filter(assegnatario=None).count(), "etichetta": "da assegnare"}],
        "grafici": [{"titolo": "Ticket aperti per priorità", "tipo": "torta", "url": reverse("helpdesk:ticket_kanban"),
                     "dati": [(etichetta, per_priorita.get(valore, 0)) for valore, etichetta in reversed(Ticket.PRIORITA)]}],
    }
