"""KPI dell'assistente per la dashboard."""
from django.urls import reverse
from django.utils import timezone

from . import limiti
from .models import Conversazione, Turno


def kpi(request):
    oggi = timezone.localdate()
    voci = [{"valore": Conversazione.objects.filter(utente=request.user).count(), "etichetta": "tue conversazioni",
             "url": reverse("ai:chat")}]
    azienda = getattr(request, "azienda", None)
    if request.user.has_perm("ai.view_turno") and azienda is not None:
        tetto = limiti.tetto(azienda)
        spesa = limiti.spesa_mese(azienda)
        voci += [{"valore": f"{spesa:.2f} $", "etichetta": f"spesa AI del mese{f' su {tetto} $' if tetto else ''}",
                  "url": reverse("ai:consumi_lista")},
                 {"valore": Turno.objects.filter(azienda=azienda, compito="chat", iniziato__date=oggi).count(),
                  "etichetta": "domande all'assistente oggi"}]
    return {"kpi": voci}
