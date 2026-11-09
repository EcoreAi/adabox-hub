from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from . import servizi
from .models import PaginaWiki


@login_required
@require_POST
def ripristina(request, pk, numero):
    pagina = get_object_or_404(PaginaWiki, pk=pk, azienda=request.azienda)
    if not servizi.puo_scrivere(request.user, pagina.spazio):
        raise PermissionDenied
    versione = get_object_or_404(pagina.versioni, numero=numero)
    servizi.ripristina(pagina, versione, request.user)
    messages.success(request, f"Ripristinata la versione {numero}: è diventata quella attuale.")
    return redirect("wiki:pagine_dettaglio", pk=pk)
