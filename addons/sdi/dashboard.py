"""KPI dello SDI per la dashboard."""
from django.urls import reverse

from core.dashboard import queryset

from django.db.models import Sum

from core.viste.gruppi import numero

from .models import FatturaPassiva, ScadenzaPassiva, Trasmissione


def kpi(request):
    qs = queryset(request, Trasmissione)
    lista = reverse("sdi:trasmissioni_lista")
    return {"kpi": [
        {"valore": qs.filter(stato__in=[Trasmissione.PRONTA, Trasmissione.INVIATA]).count(),
         "etichetta": "in attesa dello SDI", "url": f"{lista}?f_stato=inviata"},
        {"valore": qs.filter(stato__in=[Trasmissione.SCARTATA, Trasmissione.ERRORE]).count(),
         "etichetta": "scartate da correggere", "url": f"{lista}?f_stato=scartata"},
        {"valore": qs.filter(stato=Trasmissione.MANCATA_CONSEGNA).count(), "etichetta": "non recapitate"},
        {"valore": queryset(request, FatturaPassiva).filter(stato=FatturaPassiva.DA_VERIFICARE).count(),
         "etichetta": "fatture ricevute da verificare", "url": reverse("sdi:passive_lista") + "?f_stato=da_verificare"},
        {"valore": f"{numero(queryset(request, ScadenzaPassiva).filter(pagata=False).aggregate(t=Sum('importo'))['t'] or 0)} €",
         "etichetta": "da pagare ai fornitori", "url": reverse("sdi:pagamenti_lista") + "?f_pagata=0"},
    ]}
