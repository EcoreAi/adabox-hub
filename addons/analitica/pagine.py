"""Imputare le righe a mano o in massa, il report per asse e la sezione sui documenti."""
import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from core.dashboard import queryset

from . import fonti, operazioni
from .models import Asse, ModelloRipartizione, Voce


def _data(testo, ripiego=None):
    try:
        return datetime.date.fromisoformat(testo) if testo else ripiego
    except ValueError:
        return ripiego


@login_required
@permission_required("analitica.add_imputazione", raise_exception=True)
def imputa(request):
    """Le righe di una fonte nel periodo, con le loro imputazioni: si scelgono e si mettono su una voce o un modello."""
    disponibili = fonti.disponibili()
    fonte = fonti.per_chiave(request.GET.get("fonte") or request.POST.get("fonte") or "") or disponibili[0]
    oggi = timezone.localdate()
    dal = _data(request.GET.get("dal"), oggi.replace(day=1) - datetime.timedelta(days=60))
    al = _data(request.GET.get("al"), oggi)
    assi = list(queryset(request, Asse))
    voci = list(queryset(request, Voce).filter(attiva=True).select_related("asse"))
    if request.method == "POST":
        ids = [int(x) for x in request.POST.getlist("riga") if x.isdigit()]
        try:
            if request.POST.get("azione") == "togli":
                asse = queryset(request, Asse).get(pk=request.POST.get("asse"))
                n = operazioni.togli(request.azienda, fonte, ids, asse)
                messages.success(request, f"Imputazioni tolte: {n}.")
            elif request.POST.get("modello"):
                modello = queryset(request, ModelloRipartizione).get(pk=request.POST["modello"])
                n = operazioni.applica_modello(request.azienda, fonte, ids, modello)
                messages.success(request, f"«{modello}» applicato a {n} righe.")
            else:
                voce = queryset(request, Voce).get(pk=request.POST.get("voce"))
                perc = Decimal((request.POST.get("percentuale") or "100").replace(",", "."))
                n = operazioni.imputa(request.azienda, fonte, ids, voce, perc, request.POST.get("aggiungi") != "1")
                messages.success(request, f"Righe imputate a {voce}: {n}.")
        except (Voce.DoesNotExist, Asse.DoesNotExist, ModelloRipartizione.DoesNotExist):
            messages.error(request, "Scegli la voce, il modello o l'asse.")
        except (InvalidOperation, ValidationError) as e:
            messages.error(request, " ".join(getattr(e, "messages", ["Percentuale non valida."])))
        ritorno = request.POST.get("ritorno", "")
        if ritorno and url_has_allowed_host_and_scheme(ritorno, {request.get_host()}):
            return redirect(ritorno)
        return redirect(f"{request.path}?fonte={fonte.chiave}&dal={request.POST.get('dal', '')}&al={request.POST.get('al', '')}"
                        + ("&senza=1" if request.POST.get("senza") else ""))
    righe = list(fonte.righe(request.azienda, dal, al).order_by("-pk")[:300])
    mappa = operazioni.imputazioni_di(fonte, righe)
    if request.GET.get("senza") == "1":
        righe = [r for r in righe if r.pk not in mappa]
    elenco = [{"r": r, "data": fonte.data(r), "documento": fonte.documento(r), "controparte": fonte.controparte(r),
               "descrizione": fonte.descrizione(r), "importo": fonte.importo(r), "imputazioni": mappa.get(r.pk, [])} for r in righe]
    return render(request, "analitica/imputa.html", {
        "fonti": disponibili, "fonte": fonte, "dal": dal, "al": al, "righe": elenco, "voci": voci, "assi": assi,
        "modelli": queryset(request, ModelloRipartizione), "senza": request.GET.get("senza") == "1"})


@login_required
@permission_required("analitica.view_imputazione", raise_exception=True)
def report(request):
    assi = list(queryset(request, Asse))
    oggi = timezone.localdate()
    dal = _data(request.GET.get("dal"), oggi.replace(month=1, day=1))
    al = _data(request.GET.get("al"), oggi)
    asse = next((a for a in assi if str(a.pk) == request.GET.get("asse")), assi[0] if assi else None)
    dati = operazioni.report(request.azienda, asse, dal, al) if asse else None
    if dati and request.GET.get("formato") == "csv":
        from fatturazione.commercialista import foglio
        n = lambda v: f"{v:.2f}".replace(".", ",")  # noqa: E731
        risposta = HttpResponse(foglio(["Codice", "Voce", "Ricavi", "Costi esterni", "Note spese", "Margine"],
                                       [[x["voce"].codice, x["voce"].nome, n(x["ricavi"]), n(x["acquisti"]), n(x["spese"]), n(x["margine"])]
                                        for x in dati["righe"]]), content_type="text/csv; charset=utf-8")
        risposta["Content-Disposition"] = f'attachment; filename="analitica-{asse.nome.lower().replace(" ", "-")}-{dal:%Y%m%d}-{al:%Y%m%d}.csv"'
        return risposta
    return render(request, "analitica/report.html", {"assi": assi, "asse": asse, "dal": dal, "al": al, "dati": dati})
