"""La pagina dell'impostazione del servizio, solo per il Global Admin."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from . import servizio
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
