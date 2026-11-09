from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render

from . import servizi


@login_required
@permission_required("riparazioni.view_riparazione", raise_exception=True)
def verifica(request):
    """Il numero di serie è in garanzia? Da quando, fino a quando, con quale consegna."""
    seriale = request.GET.get("seriale", "").strip()
    esito = servizi.garanzia(request.azienda, seriale=seriale) if seriale else None
    return render(request, "riparazioni/verifica.html", {"seriale": seriale, "esito": esito})
