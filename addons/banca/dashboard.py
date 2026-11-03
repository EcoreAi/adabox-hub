"""KPI della banca per la dashboard."""
from django.db.models import Sum
from django.urls import reverse

from core.dashboard import numero, queryset

from .models import Conto, MovimentoBanca


def kpi(request):
    aperti = queryset(request, MovimentoBanca).filter(stato__in=(MovimentoBanca.DA_ABBINARE, MovimentoBanca.PARZIALE))
    saldo = queryset(request, Conto).filter(attivo=True).aggregate(t=Sum("saldo"))["t"]
    voci = [{"valore": aperti.count(), "etichetta": "movimenti da abbinare", "url": reverse("banca:riconcilia")}]
    if saldo is not None:
        voci.append({"valore": f"{numero(saldo)} €", "etichetta": "ultimo saldo dei conti"})
    return {"kpi": voci, "grafici": []}
