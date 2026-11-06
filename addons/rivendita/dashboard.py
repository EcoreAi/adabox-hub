import datetime

from django.urls import reverse
from django.utils import timezone

from core.dashboard import numero, queryset

from .models import Istanza, Richiesta


def dati(request):
    istanze = queryset(request, Istanza).filter(attiva=True)
    oggi = timezone.localdate()
    canone = sum(i.piano.prezzo_mese + sum(m.prezzo_mese for m in i.moduli_extra.all()) for i in istanze.select_related("piano").prefetch_related("moduli_extra"))
    per_piano = {}
    for i in istanze.select_related("piano"):
        per_piano[i.piano.nome] = per_piano.get(i.piano.nome, 0) + 1
    return {"kpi": [{"valore": istanze.count(), "etichetta": "istanze attive"},
                    {"valore": f"{numero(canone)} €", "etichetta": "canoni al mese"},
                    {"valore": queryset(request, Richiesta).filter(stato=Richiesta.NUOVA).count(), "etichetta": "richieste nuove"},
                    {"valore": istanze.filter(scadenza__lte=oggi + datetime.timedelta(days=60)).count(), "etichetta": "licenze in scadenza entro 60 giorni"}],
            "grafici": [{"titolo": "Istanze per piano", "tipo": "torta", "dati": list(per_piano.items()), "url": reverse("rivendita:istanze_lista")}]}
