"""La scheda del riepilogo: come finestra sopra la pagina (htmx) o come pagina intera."""
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import accessi, motore

PERMESSO = "riepilogo.view_preferenza"


def _contesto(request):
    p = accessi.di(request.user)
    scelta = request.GET.get("da", "accesso")
    if scelta not in dict(motore.SCELTE):
        scelta = "accesso"
    dal, testo = motore.da_quando(p, scelta)
    dati = motore.calcola(request, dal)
    p.aperto_il = timezone.now()
    p.save(update_fields=["aperto_il"])
    return {"preferenza": p, "scelta": scelta, "scelte": motore.SCELTE, "dal_testo": testo, "saluto": motore.saluto(request.user), **dati}


@login_required
@permission_required(PERMESSO, raise_exception=True)
def pannello(request):
    if request.GET.get("apertura") == "login":
        request.session.pop(accessi.CHIAVE_SESSIONE, None)
    return render(request, "riepilogo/_pannello.html", _contesto(request))


@login_required
@permission_required(PERMESSO, raise_exception=True)
def pagina(request):
    request.session.pop(accessi.CHIAVE_SESSIONE, None)
    return render(request, "riepilogo/pagina.html", _contesto(request))


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def preferenza(request):
    """Solo la propria: «apri da solo quando accedo»."""
    p = accessi.di(request.user)
    p.mostra_al_login = request.POST.get("mostra") == "1"
    p.save(update_fields=["mostra_al_login"])
    return HttpResponse(status=204)
