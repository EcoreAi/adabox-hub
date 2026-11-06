from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from contatti.models import Contatto
from core.dashboard import queryset

from . import accesso, inviti, sezioni
from .models import AccessoPortale


@accesso.portale
def home(request):
    """La home del cliente: una scheda per ogni sezione delle app installate, con i numeri e gli ultimi documenti."""
    return render(request, "portale/home.html", accesso.contesto(request, sezioni=sezioni.per(request.accesso, con_riepilogo=True)))


@login_required
@require_POST
def invita_contatto(request, pk):
    if not request.user.has_perm("portale.add_accessoportale"):
        raise PermissionDenied
    contatto = get_object_or_404(queryset(request, Contatto), pk=pk)
    try:
        inviti.invita(contatto, request.user)
    except ValueError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Invito al portale mandato a {contatto.email}.")
    return redirect("contatti:contatti_dettaglio", pk=pk)


@login_required
@require_POST
def revoca_contatto(request, pk):
    if not request.user.has_perm("portale.delete_accessoportale"):
        raise PermissionDenied
    contatto = get_object_or_404(queryset(request, Contatto), pk=pk)
    inviti.sospendi(get_object_or_404(AccessoPortale, contatto=contatto))
    messages.success(request, f"Accesso al portale di {contatto} sospeso.")
    return redirect("contatti:contatti_dettaglio", pk=pk)
