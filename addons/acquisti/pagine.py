"""Pagine degli Acquisti: proposte di riordino, valutazione dei fornitori, aggiudicazione e collegamento delle fatture."""
import datetime
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.dashboard import queryset

from . import operazioni, riordino as motore, riscontro, valutazione as pagella
from .models import FatturaOrdine, Gara, OrdineAcquisto


def _azienda(request):
    """Senza un'azienda corrente queste pagine non hanno dati da mostrare."""
    azienda = request.azienda if getattr(request.azienda, "pk", None) else None
    if azienda is None:
        raise PermissionDenied
    return azienda


def _ritorno(request, ripiego):
    url = request.POST.get("ritorno", "")
    return redirect(url) if url and url_has_allowed_host_and_scheme(url, {request.get_host()}) else redirect(ripiego)


@login_required
@permission_required("acquisti.view_ordineacquisto", raise_exception=True)
def riordino(request):
    azienda = _azienda(request)
    return render(request, "acquisti/riordino.html", {
        "disponibile": motore.disponibile(), "voci": motore.proposte(azienda),
        "puo_creare": request.user.has_perm("acquisti.add_ordineacquisto")})


@login_required
@permission_required("acquisti.add_ordineacquisto", raise_exception=True)
@require_POST
def riordino_crea(request):
    azienda = _azienda(request)
    scelti = {int(p) for p in request.POST.getlist("prodotto") if p.isdigit()}
    voci = [v for v in motore.proposte(azienda) if v["prodotto"].pk in scelti]     # ricalcolate: mai quantità dal browser
    ordini = motore.crea_richieste(azienda, voci, request.user)
    senza = sum(v["fornitore"] is None for v in voci)
    if ordini:
        messages.success(request, f"Richieste create: {', '.join(str(o) for o in ordini)}.")
    if senza:
        messages.warning(request, f"{senza} prodotti senza fornitore: aggiungili al listino o a una regola di riordino.")
    if not ordini and not senza:
        messages.warning(request, "Nessun prodotto scelto.")
    return redirect("acquisti:riordino")


def _data(testo, ripiego):
    try:
        return datetime.date.fromisoformat(testo)
    except (TypeError, ValueError):
        return ripiego


@login_required
@permission_required("acquisti.view_ordineacquisto", raise_exception=True)
def valutazione(request):
    azienda = _azienda(request)
    oggi = timezone.localdate()
    dal = _data(request.GET.get("dal"), oggi - datetime.timedelta(days=365))
    al = _data(request.GET.get("al"), oggi)
    return render(request, "acquisti/valutazione.html", {"righe": pagella.schede(azienda, dal, al), "dal": dal, "al": al})


@login_required
@permission_required("acquisti.change_ordineacquisto", raise_exception=True)
@require_POST
def aggiudica(request, pk, ordine):
    gara = get_object_or_404(queryset(request, Gara), pk=pk)
    offerta = get_object_or_404(queryset(request, OrdineAcquisto), pk=ordine, gara=gara)
    try:
        confermato = operazioni.aggiudica(gara, offerta, request.user)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    else:
        messages.success(request, f"Gara aggiudicata a {offerta.fornitore}." if confermato else
                         f"Offerta di {offerta.fornitore} inviata in approvazione: la gara si chiude quando è confermata.")
    return redirect("acquisti:gare_dettaglio", pk=gara.pk)


@login_required
@permission_required("acquisti.change_ordineacquisto", raise_exception=True)
@require_POST
def collega_fattura(request):
    if not apps.is_installed("sdi"):
        raise PermissionDenied
    from sdi.models import FatturaPassiva
    ordine = get_object_or_404(queryset(request, OrdineAcquisto), pk=request.POST.get("ordine") or 0)
    fattura = get_object_or_404(queryset(request, FatturaPassiva), pk=request.POST.get("fattura") or 0)
    testo = request.POST.get("importo", "").strip().replace(",", ".")
    try:
        importo = Decimal(testo) if testo else None
        riscontro.collega(ordine, fattura, importo, request.user)
    except InvalidOperation:
        messages.error(request, "Importo non valido.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    else:
        messages.success(request, f"Fattura {fattura.numero} collegata a {ordine}.")
    return _ritorno(request, "acquisti:ordini_lista")


@login_required
@permission_required("acquisti.change_ordineacquisto", raise_exception=True)
@require_POST
def scollega_fattura(request, pk):
    collegamento = get_object_or_404(FatturaOrdine, pk=pk, ordine__in=queryset(request, OrdineAcquisto))
    riscontro.scollega(collegamento, request.user)
    messages.success(request, "Fattura scollegata.")
    return _ritorno(request, "acquisti:ordini_lista")
