"""Giacenze: per ogni bene attivo la quantità per magazzino, il totale e il confronto con la scorta minima."""
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Sum
from django.shortcuts import render

from core.dashboard import queryset
from prodotti.models import Prodotto

from .models import Magazzino, Movimento


def situazione(request, solo_sotto_scorta=False, cerca="", alla=None):
    prodotti = queryset(request, Prodotto).filter(tipo=Prodotto.BENE, attivo=True).select_related("unita")
    if cerca:
        prodotti = prodotti.filter(nome__icontains=cerca) | prodotti.filter(codice__icontains=cerca)
    magazzini = list(queryset(request, Magazzino))
    saldi = {}
    movimenti = queryset(request, Movimento)
    if alla is not None:
        movimenti = movimenti.filter(data__lte=alla)
    for r in (movimenti.values("prodotto", "magazzino").annotate(t=Sum("quantita"))):
        saldi[(r["prodotto"], r["magazzino"])] = r["t"]
    from .models import ScortaMagazzino, impegni_e_arrivi
    azienda = getattr(request, "azienda", None)
    impegni, arrivi = impegni_e_arrivi(azienda) if azienda and alla is None else ({}, {})
    scorte = {}
    for sc in queryset(request, ScortaMagazzino):
        scorte[(sc.prodotto_id, sc.magazzino_id)] = sc.punto_riordino
    righe = []
    for p in prodotti:
        per_magazzino = [saldi.get((p.pk, m.pk), 0) for m in magazzini]
        totale = sum(per_magazzino)
        impegnato = sum((impegni.get((p.pk, m.pk), 0) for m in magazzini), 0)
        in_arrivo = sum((arrivi.get((p.pk, m.pk), 0) for m in magazzini), 0)
        previsto = totale + in_arrivo - impegnato
        sotto_magazzino = [m.nome for m in magazzini if (p.pk, m.pk) in scorte and
                           saldi.get((p.pk, m.pk), 0) + arrivi.get((p.pk, m.pk), 0) - impegni.get((p.pk, m.pk), 0) < scorte[(p.pk, m.pk)]]
        sotto = (p.scorta_minima > 0 and previsto < p.scorta_minima) or bool(sotto_magazzino)
        if solo_sotto_scorta and not sotto:
            continue
        righe.append({"prodotto": p, "per_magazzino": per_magazzino, "totale": totale, "sotto_scorta": sotto, "impegnato": impegnato,
                      "in_arrivo": in_arrivo, "previsto": previsto, "sotto_magazzino": sotto_magazzino})
    return magazzini, righe


@login_required
@permission_required("magazzino.view_movimento", raise_exception=True)
def giacenze(request):
    """Giacenze di oggi con il previsto, oppure a una data passata (solo le quantità); CSV con le stesse colonne."""
    from django.utils import timezone
    giorno, alla = _alla(request)
    passato = giorno < timezone.localdate()
    magazzini, righe = situazione(request, request.GET.get("sotto_scorta") == "1", request.GET.get("q", "").strip(),
                                  alla if passato else None)
    if passato:
        righe = [r for r in righe if r["totale"]]
    if request.GET.get("formato") == "csv" and _csv_disponibile():
        from django.http import HttpResponse

        from fatturazione.commercialista import foglio
        n = lambda v: f"{v:.3f}".replace(".", ",")  # noqa: E731
        testata = ["Codice", "Prodotto", "Unità", *[m.nome for m in magazzini], "Totale"] + ([] if passato else ["Impegnato", "In arrivo", "Previsto", "Scorta minima"])
        dati = [[r["prodotto"].codice, r["prodotto"].nome, str(r["prodotto"].unita), *[n(q) for q in r["per_magazzino"]], n(r["totale"])]
                + ([] if passato else [n(r["impegnato"]), n(r["in_arrivo"]), n(r["previsto"]), n(r["prodotto"].scorta_minima)]) for r in righe]
        risposta = HttpResponse(foglio(testata, dati), content_type="text/csv; charset=utf-8")
        risposta["Content-Disposition"] = f'attachment; filename="giacenze-{giorno:%Y-%m-%d}.csv"'
        return risposta
    return render(request, "magazzino/giacenze.html", {"magazzini": magazzini, "righe": righe, "giorno": giorno, "passato": passato,
                                                        "csv": _csv_disponibile()})


FASCE = [(30, "fino a 30 giorni"), (90, "31–90"), (180, "91–180"), (365, "181–365"), (None, "oltre un anno")]


def anzianita_di(prodotti, oggi):
    """[{prodotto, quantita, fasce: [q per fascia], valore, piu_vecchio}]: la giacenza di oggi attribuita agli ultimi
    carichi (chi entra per primo esce per primo), così si vede da quanto è ferma la merce. Trasferimenti esclusi."""
    from . import costi
    righe = []
    for p in prodotti:
        giacenza = Movimento.objects.filter(prodotto=p).aggregate(t=Sum("quantita"))["t"] or 0
        if giacenza <= 0:
            continue
        resto, fasce, piu_vecchio = giacenza, [0] * len(FASCE), None
        for m in Movimento.objects.filter(prodotto=p, quantita__gt=0).exclude(tipo=Movimento.TRASFERIMENTO).order_by("-data", "-pk"):
            presa = min(resto, m.quantita)
            from django.utils import timezone
            giorni = (oggi - timezone.localtime(m.data).date()).days
            indice = next(i for i, (limite, _) in enumerate(FASCE) if limite is None or giorni <= limite)
            fasce[indice] += presa
            piu_vecchio = m.data
            resto -= presa
            if resto <= 0:
                break
        if resto > 0:                                       # senza carichi abbastanza: la parte che resta è la più vecchia
            fasce[-1] += resto
        costo = costi.costo_corrente(p)
        righe.append({"prodotto": p, "quantita": giacenza, "fasce": fasce, "valore": costi.q2(giacenza * costo), "piu_vecchio": piu_vecchio,
                      "costo": costo})
    return righe


@login_required
@permission_required("magazzino.view_movimento", raise_exception=True)
def anzianita(request):
    from django.utils import timezone
    oggi = timezone.localdate()
    prodotti = queryset(request, Prodotto).filter(tipo=Prodotto.BENE).select_related("unita").order_by("nome")
    righe = anzianita_di(prodotti, oggi)
    totali = [sum((r["fasce"][i] * r["costo"] for r in righe), 0) for i in range(len(FASCE))]
    if request.GET.get("formato") == "csv" and _csv_disponibile():
        from django.http import HttpResponse

        from fatturazione.commercialista import foglio
        n = lambda v, d=3: f"{v:.{d}f}".replace(".", ",")  # noqa: E731
        risposta = HttpResponse(foglio(["Codice", "Prodotto", "Giacenza", *[nome for _, nome in FASCE], "Valore", "Carico più vecchio"],
                                       [[r["prodotto"].codice, r["prodotto"].nome, n(r["quantita"]), *[n(q) for q in r["fasce"]], n(r["valore"], 2),
                                         r["piu_vecchio"].strftime("%d/%m/%Y") if r["piu_vecchio"] else ""] for r in righe]),
                                content_type="text/csv; charset=utf-8")
        risposta["Content-Disposition"] = f'attachment; filename="anzianita-magazzino-{oggi:%Y-%m-%d}.csv"'
        return risposta
    return render(request, "magazzino/anzianita.html", {"righe": righe, "fasce": [nome for _, nome in FASCE],
                                                         "totali": [(FASCE[i][1], t) for i, t in enumerate(totali)], "csv": _csv_disponibile()})


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


def _posti(request):
    """Scelte «magazzino» e «magazzino · ubicazione» dell'azienda: m<pk> e u<pk>."""
    from .models import Ubicazione
    scelte = []
    for m in queryset(request, Magazzino):
        scelte.append((f"m{m.pk}", f"{m.nome} (senza ubicazione)"))
        scelte += [(f"u{u.pk}", f"{m.nome} · {u.percorso}" + (f" — {u.nome}" if u.nome else ""))
                   for u in Ubicazione.objects.filter(magazzino=m, attiva=True).select_related("padre")]
    return scelte


def _posto(request, valore):
    from .models import Ubicazione
    if valore.startswith("u") and valore[1:].isdigit():
        u = queryset(request, Ubicazione).filter(pk=valore[1:]).select_related("magazzino").first()
        return (u.magazzino, u) if u else (None, None)
    if valore.startswith("m") and valore[1:].isdigit():
        return queryset(request, Magazzino).filter(pk=valore[1:]).first(), None
    return None, None


@login_required
@permission_required("magazzino.add_movimento", raise_exception=True)
def trasferisci(request):
    from decimal import Decimal, InvalidOperation

    from django.contrib import messages
    from django.core.exceptions import ValidationError
    from django.shortcuts import redirect

    from . import operazioni
    prodotti = queryset(request, Prodotto).filter(tipo=Prodotto.BENE, attivo=True).order_by("nome")
    posti = _posti(request)
    dati = request.POST if request.method == "POST" else request.GET
    if request.method == "POST":
        prodotto = prodotti.filter(pk=dati.get("prodotto")).first() if str(dati.get("prodotto", "")).isdigit() else None
        da_m, da_u = _posto(request, dati.get("da", ""))
        a_m, a_u = _posto(request, dati.get("a", ""))
        try:
            quantita = Decimal(str(dati.get("quantita", "")).replace(",", "."))
        except InvalidOperation:
            quantita = None
        from .models import Lotto
        codice = dati.get("lotto", "").strip()
        lotto = Lotto.objects.filter(prodotto=prodotto, codice=codice).first() if prodotto and codice else None
        if prodotto is None or da_m is None or a_m is None or quantita is None:
            messages.error(request, "Scegli prodotto, quantità, partenza e arrivo.")
        elif codice and lotto is None:
            messages.error(request, f"Il lotto {codice} non esiste per {prodotto}.")
        else:
            try:
                operazioni.trasferisci(prodotto, quantita, da_m, a_m, da_u, a_u, request.user, dati.get("causale", "").strip(),
                                       lotto)
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
            else:
                messages.success(request, f"Spostati {quantita:g} di {prodotto}.")
                return redirect(f"{request.path}?da={dati.get('da')}")
    return render(request, "magazzino/trasferisci.html", {"prodotti": prodotti, "posti": posti, "dati": dati})


@login_required
@permission_required("magazzino.view_movimento", raise_exception=True)
def per_ubicazione(request):
    """La merce posto per posto in un magazzino."""
    magazzini = list(queryset(request, Magazzino))
    scelto = next((m for m in magazzini if str(m.pk) == request.GET.get("magazzino")), magazzini[0] if magazzini else None)
    righe = contenuto(scelto) if scelto else []
    return render(request, "magazzino/per_ubicazione.html", {"magazzini": magazzini, "scelto": scelto, "righe": righe})


def contenuto(magazzino, ubicazione=None):
    """[{ubicazione, prodotto, quantita}] con quantità diversa da zero, ordinate per ubicazione."""
    from .models import Ubicazione
    qs = Movimento.objects.filter(magazzino=magazzino)
    if ubicazione is not None:
        qs = qs.filter(ubicazione=ubicazione)
    saldi = qs.values("ubicazione", "prodotto").annotate(t=Sum("quantita")).exclude(t=0)
    ubicazioni = {u.pk: u for u in Ubicazione.objects.filter(magazzino=magazzino).select_related("padre")}
    prodotti = {p.pk: p for p in Prodotto.objects.filter(pk__in={s["prodotto"] for s in saldi}).select_related("unita")}
    righe = [{"ubicazione": ubicazioni.get(s["ubicazione"]), "prodotto": prodotti[s["prodotto"]], "quantita": s["t"]} for s in saldi]
    return sorted(righe, key=lambda r: (r["ubicazione"] is None, r["ubicazione"].percorso if r["ubicazione"] else "", r["prodotto"].nome))


@login_required
@permission_required("magazzino.change_lotto", raise_exception=True)
def tracciamento_prodotto(request, pk):
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    from .models import Tracciamento
    prodotto = get_object_or_404(queryset(request, Prodotto), pk=pk)
    if request.method == "POST":
        tipo = request.POST.get("tipo", "")
        if tipo not in {"", Tracciamento.LOTTO, Tracciamento.SERIALE}:
            messages.error(request, "Tracciamento non valido.")
        elif tipo and giacenza_senza_lotto(prodotto):
            messages.error(request, "C'è merce di questo prodotto senza lotto: azzerala con una rettifica, poi ricaricala con i lotti.")
        else:
            Tracciamento.objects.update_or_create(prodotto=prodotto, defaults={"tipo": tipo, "scadenza": request.POST.get("scadenza") == "1"})
            messages.success(request, "Tracciamento salvato.")
    return redirect("prodotti:prodotti_dettaglio", prodotto.pk)


def giacenza_senza_lotto(prodotto):
    return Movimento.objects.filter(prodotto=prodotto, lotto__isnull=True).aggregate(t=Sum("quantita"))["t"] or 0
