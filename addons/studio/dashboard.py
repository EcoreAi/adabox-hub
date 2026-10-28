"""KPI di Studio per la dashboard."""
from core.models import CampoPersonalizzato

from .models import Personalizzazione


def kpi(request):
    if not request.user.has_perm("studio.change_personalizzazione"):
        return {"kpi": []}
    return {"kpi": [{"valore": Personalizzazione.objects.exclude(dati={}).count(), "etichetta": "viste personalizzate"},
                    {"valore": CampoPersonalizzato.objects.count(), "etichetta": "campi personalizzati"}]}
