"""Pagine proprie della Fatturazione: la fattura da un ordine di vendita."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from core.dashboard import queryset
from vendite.models import OrdineVendita

from . import operazioni


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
