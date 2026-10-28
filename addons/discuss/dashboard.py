"""KPI di Discuss per la dashboard."""
from django.urls import reverse

from . import servizi


def kpi(request):
    if not request.user.has_perm("discuss.view_canale"):
        return {"kpi": []}
    iscrizioni = list(servizi.iscrizioni_di(request.user))
    return {"kpi": [
        {"valore": sum(i.non_letti or 0 for i in iscrizioni), "etichetta": "messaggi non letti",
         "url": reverse("discuss:home")},
        {"valore": len(iscrizioni), "etichetta": "conversazioni"},
    ]}
