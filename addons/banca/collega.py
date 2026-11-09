"""Pagine del collegamento automatico di un conto: scegliere la banca, dare il consenso, leggere adesso, scollegare."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.dashboard import queryset

from . import sincronia
from .models import CollegamentoConto, Conto

PERMESSO = "banca.add_collegamentoconto"


@login_required
@permission_required(PERMESSO, raise_exception=True)
def collega(request, pk):
    """Sceglie la banca e manda al suo sito per il consenso."""
    conto = get_object_or_404(queryset(request, Conto), pk=pk)
    aggregatore = sincronia.aggregatore_attivo(conto.azienda)
    if aggregatore is None:
        messages.error(request, "Prima configura il servizio di lettura dei conti.")
        return redirect("banca:aggregatori_lista")
    if request.method == "POST":
        istituto = request.POST.get("istituto", "").strip()
        try:
            elenco = {b["id"]: b for b in sincronia.banche(aggregatore)}
            if istituto not in elenco:
                messages.error(request, "Scegli la banca dall'elenco.")
                return redirect("banca:collega", pk=conto.pk)
            giorni = min(int(elenco[istituto].get("transaction_total_days") or 90), 90)
            c = sincronia.avvia(conto, aggregatore, istituto, elenco[istituto].get("name", ""), giorni, request.user)
        except sincronia.ErroreBanca as e:
            messages.error(request, f"Il collegamento non è partito: {e}")
            return redirect("banca:conti_dettaglio", pk=conto.pk)
        return redirect(c.link_consenso)
    try:
        elenco = sincronia.banche(aggregatore)
    except sincronia.ErroreBanca as e:
        messages.error(request, f"Non riesco ad avere l'elenco delle banche: {e}")
        return redirect("banca:conti_dettaglio", pk=conto.pk)
    return render(request, "banca/collega.html", {"conto": conto, "banche": sorted(elenco, key=lambda b: b.get("name", "").lower()),
                                                  "aggregatore": aggregatore})


@login_required
@permission_required(PERMESSO, raise_exception=True)
def ritorno(request, pk):
    """Il ritorno dal sito della banca: si attiva il collegamento e si leggono subito i movimenti."""
    c = get_object_or_404(queryset(request, CollegamentoConto).select_related("conto", "aggregatore"), pk=pk)
    if request.GET.get("error"):
        messages.error(request, "La banca non ha dato il consenso: puoi riprovare quando vuoi.")
        return redirect("banca:conti_dettaglio", pk=c.conto_id)
    try:
        sincronia.completa(c)
        esito = sincronia.leggi(c, request.user)
    except sincronia.ErroreBanca as e:
        c.stato, c.errore = CollegamentoConto.ERRORE, str(e)[:300]
        c.save(update_fields=["stato", "errore"])
        messages.error(request, f"CollegamentoConto non riuscito: {e}")
        return redirect("banca:conti_dettaglio", pk=c.conto_id)
    messages.success(request, f"Conto collegato: movimenti nuovi {esito.nuovi if esito else 0}. D'ora in poi arrivano da soli.")
    return redirect("banca:conti_dettaglio", pk=c.conto_id)


@login_required
@permission_required("banca.add_importazione", raise_exception=True)
@require_POST
def leggi_ora(request, pk):
    c = get_object_or_404(queryset(request, CollegamentoConto), pk=pk)
    try:
        esito = sincronia.leggi(c, request.user)
    except sincronia.ErroreBanca as e:
        messages.error(request, f"Lettura non riuscita: {e}")
    else:
        if esito is None:
            messages.warning(request, "Il collegamento non è attivo: rinnova il consenso.")
        else:
            messages.success(request, f"Movimenti nuovi: {esito.nuovi}." + (f" Già presenti: {esito.doppi}." if esito.doppi else ""))
    return redirect("banca:conti_dettaglio", pk=c.conto_id)


@login_required
@permission_required("banca.delete_collegamentoconto", raise_exception=True)
@require_POST
def scollega(request, pk):
    c = get_object_or_404(queryset(request, CollegamentoConto), pk=pk)
    conto = c.conto_id
    c.delete()
    messages.success(request, "CollegamentoConto tolto: i movimenti già letti restano.")
    return redirect("banca:conti_dettaglio", pk=conto)
