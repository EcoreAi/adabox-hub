"""La pagina dello scadenziario dei clienti."""
from django.contrib.auth.decorators import login_required, permission_required
from django.urls import reverse

from . import scadenzario as motore


@login_required
@permission_required("fatturazione.view_scadenza", raise_exception=True)
def scadenzario(request):
    elenco = reverse("fatturazione:scadenze_lista")
    return motore.risposta(request, motore.voci_clienti(request), "Scadenziario clienti", "Cliente", "scadenziario-clienti",
                           lambda pk: f"{elenco}?f_pagata=0&f_fattura__cliente={pk}")
