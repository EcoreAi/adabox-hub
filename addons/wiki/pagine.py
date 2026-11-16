from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
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


@login_required
@permission_required("wiki.view_paginawiki", raise_exception=True)
def chiedi(request):
    """La domanda va all'assistente in una chat limitata alla wiki: risponde solo con le pagine che chi chiede può
    leggere, e cita le sezioni."""
    azienda = getattr(request, "azienda", None)
    spazi = servizi.spazi_leggibili(request.user, azienda) if azienda else []
    return render(request, "wiki/chiedi.html", {
        "si_puo": servizi.si_puo_chiedere(request.user), "pagine": PaginaWiki.objects.filter(spazio__in=spazi).count(),
        "domande": request.user.has_perm("wiki.view_domandawiki")})
