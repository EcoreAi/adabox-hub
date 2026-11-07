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


def _alla(request):
    import datetime

    from django.utils import timezone
    valore = request.GET.get("data", "")
    try:
        giorno = datetime.date.fromisoformat(valore) if valore else timezone.localdate()
    except ValueError:
        giorno = timezone.localdate()
    return giorno, timezone.make_aware(datetime.datetime.combine(giorno, datetime.time.max))


@login_required
@permission_required("magazzino.view_movimento", raise_exception=True)
def valore(request):
    """Inventario valorizzato a una data, con il metodo di costo di ogni prodotto."""
    from django.http import HttpResponse

    from . import costi
    giorno, alla = _alla(request)
    prodotti = list(queryset(request, Prodotto).filter(tipo=Prodotto.BENE).select_related("metodo_costo", "unita"))
    righe = costi.valorizzazione(prodotti, alla)
    for r in righe:
        r["nome_metodo"] = dict(costi.METODI)[r["metodo"]]
    totale = sum((r["valore"] for r in righe), 0)
    if request.GET.get("formato") == "csv":
        from fatturazione.commercialista import foglio
        risposta = HttpResponse(foglio(["Codice", "Prodotto", "Metodo", "Quantità", "Costo unitario", "Valore"],
                                       [[r["prodotto"].codice, r["prodotto"].nome, dict(costi.METODI)[r["metodo"]],
                                         f"{r['quantita']:.3f}".replace(".", ","), f"{r['costo']:.4f}".replace(".", ","),
                                         f"{r['valore']:.2f}".replace(".", ",")] for r in righe]),
                                content_type="text/csv; charset=utf-8")
        risposta["Content-Disposition"] = f'attachment; filename="valore-magazzino-{giorno:%Y-%m-%d}.csv"'
        return risposta
    return render(request, "magazzino/valore.html", {
        "righe": righe, "totale": totale, "giorno": giorno, "metodo": dict(costi.METODI)[costi.metodo_azienda(request.azienda)],
        "negative": [r for r in righe if r["quantita"] < 0],
        "csv": _csv_disponibile()})


def _csv_disponibile():
    from django.apps import apps
    return apps.is_installed("fatturazione")


@login_required
@permission_required("magazzino.add_movimento", raise_exception=True)
def ricalcola(request):
    from django.contrib import messages
    from django.shortcuts import redirect

    from . import costi
    if request.method == "POST":
        cambiati = sum(costi.ricalcola(p) for p in queryset(request, Prodotto).filter(tipo=Prodotto.BENE, movimenti__isnull=False).distinct())
        messages.success(request, f"Costi ricalcolati: {cambiati} movimenti aggiornati.")
    return redirect("magazzino:valore")


@login_required
@permission_required("magazzino.add_movimento", raise_exception=True)
def metodo_prodotto(request, pk):
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    from . import costi
    from .models import MetodoCosto
    prodotto = get_object_or_404(queryset(request, Prodotto), pk=pk)
    if request.method == "POST":
        scelta = request.POST.get("metodo", "")
        if scelta not in {"", costi.MEDIO, costi.FIFO, costi.STANDARD}:
            messages.error(request, "Metodo non valido.")
        else:
            MetodoCosto.objects.update_or_create(prodotto=prodotto, defaults={"metodo": scelta})
            prodotto.refresh_from_db()
            n = costi.ricalcola(prodotto)
            messages.success(request, f"Metodo di costo salvato; movimenti ricalcolati: {n}.")
    return redirect("prodotti:prodotti_dettaglio", prodotto.pk)
