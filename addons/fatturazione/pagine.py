"""Pagine proprie della Fatturazione: la fattura da un ordine di vendita, gli incassi dalla fattura."""
import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.dashboard import queryset
from vendite.models import OrdineVendita

from . import operazioni
from .models import Fattura, Incasso


@login_required
@permission_required("fatturazione.add_fattura", raise_exception=True)
@require_POST
def da_ordine(request, pk):
    ordine = queryset(request, OrdineVendita).filter(pk=pk).first()
    if ordine is None:
        messages.error(request, "Ordine non trovato.")
        return redirect("vendite:ordini_lista")
    try:
        fattura = operazioni.da_ordine(ordine)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("vendite:ordini_dettaglio", pk=ordine.pk)
    messages.success(request, f"Fattura in bozza creata dall'ordine {ordine.numero_ordine}.")
    return redirect("fatturazione:fatture_dettaglio", pk=fattura.pk)


@login_required
@require_POST
@permission_required("fatturazione.change_scadenza", raise_exception=True)
def incasso(request, pk):
    fattura = get_object_or_404(queryset(request, Fattura), pk=pk)
    try:
        importo = Decimal(request.POST.get("importo") or "0")
        data = datetime.date.fromisoformat(request.POST.get("data") or timezone.localdate().isoformat())
        operazioni.incassa_fattura(fattura, importo, data, request.POST.get("metodo", "bonifico"),
                                   request.POST.get("tipo", Incasso.INCASSO), request.POST.get("riferimento", "")[:120], request.user)
    except (InvalidOperation, ValueError):
        messages.error(request, "Controlla importo e data.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    else:
        messages.success(request, "Fattura incassata per intero." if Fattura.objects.get(pk=pk).pagata else "Incasso registrato.")
    return redirect("fatturazione:fatture_dettaglio", pk=pk)


@login_required
@require_POST
@permission_required("fatturazione.change_scadenza", raise_exception=True)
def incasso_annulla(request, pk):
    voce = get_object_or_404(Incasso.objects.select_related("scadenza__fattura"), pk=pk,
                             scadenza__fattura__in=queryset(request, Fattura))
    fattura_pk = voce.scadenza.fattura_id
    operazioni.annulla_incasso(voce)
    messages.success(request, "Incasso annullato.")
    return redirect("fatturazione:fatture_dettaglio", pk=fattura_pk)
