"""Dalle ore alla fattura: l'elenco dei progetti con ore aperte, la scelta delle righe, le ore dal ticket."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.dashboard import queryset
from fatturazione.models import Fattura
from helpdesk.models import Ticket
from progetti.models import Progetto
from timesheet.models import RigaOre

from . import operazioni
from .models import Condizioni, FatturaProgetto


def _progetto(request, pk):
    return get_object_or_404(queryset(request, Progetto), pk=pk)


@login_required
@permission_required("commesse.view_condizioni", raise_exception=True)
def da_fatturare(request):
    aperti = RigaOre.objects.filter(azienda=request.azienda, fatturabile=True, bloccata=False).values_list("progetto", flat=True)
    schede = []
    for progetto in queryset(request, Progetto).filter(pk__in=set(aperti)).select_related("cliente"):
        voci = operazioni.da_fatturare(progetto)
        if voci:
            schede.append({"progetto": progetto, "ore": sum(v["ore"] for v in voci), "importo": sum(v["importo"] for v in voci),
                           "senza_tariffa": any(not v["tariffa"] for v in voci)})
    return render(request, "commesse/da_fatturare.html", {"schede": sorted(schede, key=lambda s: -s["importo"]),
                                                          "totale": sum((s["importo"] for s in schede), Decimal(0))})


@login_required
@permission_required("fatturazione.add_fattura", raise_exception=True)
def fattura_ore(request, pk):
    progetto = _progetto(request, pk)
    if request.method == "POST":
        scelte = [int(p) for p in request.POST.getlist("riga") if p.isdigit()]
        try:
            fattura = operazioni.fattura_ore(progetto, scelte)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return redirect("commesse:fattura_ore", pk=pk)
        messages.success(request, f"{fattura} creata: controllala ed emettila.")
        return redirect("fatturazione:fatture_dettaglio", pk=fattura.pk)
    return render(request, "commesse/fattura_ore.html", {"progetto": progetto, "voci": operazioni.da_fatturare(progetto),
                                                         "condizioni": operazioni.condizioni_di(progetto)})


@login_required
@permission_required("fatturazione.add_fattura", raise_exception=True)
@require_POST
def fattura_corpo(request, pk):
    try:
        fattura = operazioni.fattura_corpo(_progetto(request, pk))
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("progetti:progetti_dettaglio", pk=pk)
    messages.success(request, f"{fattura} creata: controllala ed emettila.")
    return redirect("fatturazione:fatture_dettaglio", pk=fattura.pk)


@login_required
@permission_required("commesse.view_condizioni", raise_exception=True)
def condizioni_progetto(request, pk):
    """Dal progetto alle sue condizioni, che nascono qui la prima volta."""
    condizioni = operazioni.condizioni_di(_progetto(request, pk))
    return redirect("commesse:condizioni_dettaglio", pk=condizioni.pk)


@login_required
@permission_required("commesse.change_condizioni", raise_exception=True)
@require_POST
def collega_fattura(request, pk):
    progetto = _progetto(request, pk)
    fattura = get_object_or_404(queryset(request, Fattura), pk=request.POST.get("fattura") or 0)
    FatturaProgetto.objects.update_or_create(fattura=fattura, defaults={"progetto": progetto})
    messages.success(request, f"{fattura} conta tra i ricavi del progetto.")
    return redirect("progetti:progetti_dettaglio", pk=pk)


@login_required
@permission_required("timesheet.add_rigaore", raise_exception=True)
@require_POST
def ore_ticket(request, pk):
    ticket = get_object_or_404(queryset(request, Ticket), pk=pk)
    try:
        ore = Decimal(request.POST.get("ore", "").replace(",", "."))
        operazioni.registra_su_ticket(ticket, request.user, ore, request.POST.get("descrizione", "")[:250])
    except InvalidOperation:
        messages.error(request, "Indica le ore con un numero, es. 1,5.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    else:
        messages.success(request, f"Registrate {ore} ore su {ticket.numero}.")
    prossima = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(prossima, {request.get_host()}, request.is_secure()):
        return redirect(prossima)
    return redirect("helpdesk:ticket_dettaglio", pk=pk)
