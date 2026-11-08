"""Dalla scheda del contatto: consenso, esportazione dei dati, anonimizzazione."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from core.viste import registry

from . import servizi
from .models import Consenso, Finalita


def _contatto(request, pk, permesso="view"):
    from contatti.models import Contatto
    from django.core.exceptions import PermissionDenied
    vista = registry.per_modello(Contatto)
    obj = vista.get_object(request, pk)                  # fuori azienda → 404
    controllo = vista.has_change_permission if permesso == "change" else vista.has_view_permission
    if not controllo(request, obj):
        raise PermissionDenied
    return vista, obj


@login_required
@permission_required("privacy.add_consenso", raise_exception=True)
@require_POST
def consenso(request, pk):
    vista, contatto = _contatto(request, pk)
    finalita = get_object_or_404(Finalita, pk=request.POST.get("finalita") or 0, attiva=True)
    fonte = request.POST.get("fonte") if request.POST.get("fonte") in dict(Consenso.FONTI) else "persona"
    servizi.registra(contatto, finalita, request.POST.get("dato") == "1", fonte, request.user, request.POST.get("note", ""))
    messages.success(request, f"Consenso «{finalita}» registrato.")
    return redirect(vista.url("dettaglio", pk=contatto.pk))


@login_required
@permission_required("privacy.esporta_dati", raise_exception=True)
def esporta(request, pk):
    _, contatto = _contatto(request, pk)
    risposta = HttpResponse(servizi.esporta_json(contatto), content_type="application/json; charset=utf-8")
    risposta["Content-Disposition"] = f'attachment; filename="dati-{slugify(contatto.nome) or contatto.pk}.json"'
    from core import chatter
    chatter.scrivi(contatto, request.user, "Dati del contatto esportati (richiesta di accesso o portabilità).", tipo="sistema")
    return risposta


@login_required
@permission_required("privacy.anonimizza_contatto", raise_exception=True)
def anonimizza(request, pk):
    """GET: che cosa succederà; POST con la conferma scritta: si anonimizza (irreversibile)."""
    vista, contatto = _contatto(request, pk, "change")
    documenti = servizi.documenti_da_conservare(contatto)
    if request.method == "POST":
        if request.POST.get("conferma", "").strip().upper() != "ANONIMIZZA":
            messages.error(request, "Per procedere scrivi ANONIMIZZA nel campo di conferma.")
            return redirect("privacy:anonimizza", pk=contatto.pk)
        try:
            esito = servizi.anonimizza(contatto, request.user)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect(vista.url("dettaglio", pk=contatto.pk))
        messages.success(request, "Contatto anonimizzato" + (" in parte: restano i dati dei documenti da conservare." if esito.parziale else "."))
        return redirect(vista.url("dettaglio", pk=contatto.pk))
    return render(request, "privacy/anonimizza.html", {"contatto": contatto, "documenti": documenti,
                                                       "url_contatto": vista.url("dettaglio", pk=contatto.pk)})
