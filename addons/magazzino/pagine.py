"""Giacenze: per ogni bene attivo la quantità per magazzino, il totale e il confronto con la scorta minima."""
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Sum
from django.shortcuts import render

from core.dashboard import queryset
from prodotti.models import Prodotto

from .models import Magazzino, Movimento


def situazione(request, solo_sotto_scorta=False, cerca=""):
    prodotti = queryset(request, Prodotto).filter(tipo=Prodotto.BENE, attivo=True).select_related("unita")
    if cerca:
        prodotti = prodotti.filter(nome__icontains=cerca) | prodotti.filter(codice__icontains=cerca)
    magazzini = list(queryset(request, Magazzino))
    saldi = {}
    for r in (queryset(request, Movimento).values("prodotto", "magazzino").annotate(t=Sum("quantita"))):
        saldi[(r["prodotto"], r["magazzino"])] = r["t"]
    righe = []
    for p in prodotti:
        per_magazzino = [saldi.get((p.pk, m.pk), 0) for m in magazzini]
        totale = sum(per_magazzino)
        sotto = p.scorta_minima > 0 and totale < p.scorta_minima
        if solo_sotto_scorta and not sotto:
            continue
        righe.append({"prodotto": p, "per_magazzino": per_magazzino, "totale": totale, "sotto_scorta": sotto})
    return magazzini, righe


@login_required
@permission_required("magazzino.view_movimento", raise_exception=True)
def giacenze(request):
    magazzini, righe = situazione(request, request.GET.get("sotto_scorta") == "1", request.GET.get("q", "").strip())
    return render(request, "magazzino/giacenze.html", {"magazzini": magazzini, "righe": righe})
