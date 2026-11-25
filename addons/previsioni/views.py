"""La pagina dell'impostazione del servizio, solo per il Global Admin, e «Aggiorna» delle previsioni salvate."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core import lavori

from . import calcolo, servizio
from .forms import ServizioForm
from .models import ServizioPrevisioni


@login_required
def pagina_servizio(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    corrente = ServizioPrevisioni.corrente()
    form = ServizioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.salva(corrente)
        messages.success(request, "Impostazione del servizio di previsione salvata.")
        return redirect("previsioni:servizio")
    return render(request, "previsioni/servizio.html", {
        "form": form, "chiave_impostata": bool(corrente.chiave_cifrata), "url_servizio": servizio.url()})


@login_required
@permission_required("previsioni.change_previsionearticolo", raise_exception=True)
@require_POST
def aggiorna(request):
    """«Aggiorna» (`?cosa=magazzino`): il ricalcolo va in un lavoro in background, perché ogni chiamata al servizio
    può durare minuti, e si torna alla pagina di prima."""
    cosa, azienda = request.GET.get("cosa", ""), getattr(request, "azienda", None)
    if cosa not in calcolo.CALCOLI or azienda is None:
        return HttpResponseBadRequest("Previsioni da aggiornare sconosciute o nessuna azienda corrente.")
    lavori.accoda("previsioni.calcolo.aggiorna", azienda=azienda, utente=request.user, max_tentativi=1,
                  azienda_id=azienda.pk, cosa=cosa)
    messages.success(request, "Aggiornamento avviato: le previsioni saranno pronte tra poco.")
    indietro = request.META.get("HTTP_REFERER", "")
    if url_has_allowed_host_and_scheme(indietro, {request.get_host()}, request.is_secure()):
        return redirect(indietro)
    return redirect("core:home")
