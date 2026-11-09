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
                                   request.POST.get("tipo", Incasso.INCASSO), request.POST.get("riferimento", "")[:120], request.user,
                                   eccedenza_a_credito=request.POST.get("eccedenza") == "1")
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



@login_required
@require_POST
@permission_required("fatturazione.change_scadenza", raise_exception=True)
def usa_credito(request, pk):
    fattura = get_object_or_404(queryset(request, Fattura), pk=pk)
    try:
        incassi = operazioni.usa_credito(fattura, request.user)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    else:
        messages.success(request, f"Usati {sum(i.importo for i in incassi):.2f} € del credito del cliente.")
    return redirect("fatturazione:fatture_dettaglio", pk=pk)



@login_required
@require_POST
@permission_required("fatturazione.change_fattura", raise_exception=True)
def posizione_contatto(request, pk):
    """La posizione fiscale scelta per il cliente: «auto» torna a quella automatica, «nessuna» la toglie."""
    from contatti.models import Contatto

    from .models import PosizioneContatto, PosizioneFiscale
    contatto = get_object_or_404(queryset(request, Contatto), pk=pk)
    scelta = request.POST.get("posizione", "auto")
    if scelta == "auto":
        PosizioneContatto.objects.filter(contatto=contatto).delete()
    else:
        posizione = PosizioneFiscale.objects.filter(pk=scelta).first() if scelta.isdigit() else None
        PosizioneContatto.objects.update_or_create(contatto=contatto, defaults={"azienda": contatto.azienda, "posizione": posizione})
    messages.success(request, "Posizione fiscale aggiornata: vale per le prossime righe.")
    return redirect("contatti:contatti_dettaglio", pk=contatto.pk)
