"""Pagine dello SDI: invio di una fattura, XML, caricamento a mano dei file ricevuti."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.dashboard import queryset
from fatturazione.models import Fattura

from . import ricezione, servizi
from .models import Trasmissione


def _alla_fattura(fattura):
    return redirect("fatturazione:fatture_dettaglio", pk=fattura.pk)


@login_required
@permission_required("sdi.add_trasmissione", raise_exception=True)
@require_POST
def invia(request, pk):
    fattura = get_object_or_404(queryset(request, Fattura), pk=pk)
    try:
        _, messaggio = servizi.invia(fattura, request.user)
    except ValidationError as e:
        for m in e.messages:
            messages.error(request, m)
    else:
        messages.success(request, messaggio)
    return _alla_fattura(fattura)


def _trasmissione(request, pk):
    azienda_id = getattr(getattr(request, "azienda", None), "pk", None)
    qs = Trasmissione.objects.all() if azienda_id is None else Trasmissione.objects.filter(azienda_id=azienda_id)
    return get_object_or_404(qs, pk=pk)


@login_required
@permission_required("sdi.view_trasmissione", raise_exception=True)
def xml(request, pk):
    t = _trasmissione(request, pk)
    with t.file.open("rb") as f:
        risposta = HttpResponse(f.read(), content_type="application/xml")
    risposta["Content-Disposition"] = f'attachment; filename="{t.nome_file}"'
    return risposta


@login_required
@permission_required("sdi.add_trasmissione", raise_exception=True)
@require_POST
def caricata(request, pk):
    t = _trasmissione(request, pk)
    if t.stato == Trasmissione.PRONTA:
        servizi.segna_caricata(t, request.user)
        messages.success(request, f"{t.nome_file} segnato come caricato: ora si attende la notifica dello SDI.")
    return _alla_fattura(t.fattura)


@login_required
@permission_required("sdi.add_notificasdi", raise_exception=True)
def carica(request):
    """Caricamento a mano di notifiche (e, con le fatture passive, di fatture dei fornitori), anche in zip."""
    esiti = []
    if request.method == "POST":
        for file in request.FILES.getlist("file")[:200]:
            esiti.extend(_appiattisci(ricezione.ricevi(file.name, file.read(), getattr(request, "azienda", None)),
                                      file.name))
        if not esiti:
            messages.warning(request, "Nessun file caricato.")
    return render(request, "sdi/carica.html", {"esiti": esiti})


def _appiattisci(risultato, nome):
    esito, oggetto = risultato
    if esito == "zip":
        return [r for i, sotto in enumerate(oggetto) for r in _appiattisci(sotto, f"{nome} [{i + 1}]")]
    return [{"esito": esito, "oggetto": oggetto, "nome": getattr(oggetto, "nome_file", None) or str(oggetto) or nome}]
