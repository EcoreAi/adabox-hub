"""Nuova distinta, file per la banca, presentazione ed esiti; impostazioni del conto e coordinate del contatto."""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from banca.models import Conto
from contatti.models import Contatto
from core.dashboard import queryset

from . import servizi
from .forms import ConfigContoForm, CoordinateForm, NuovaForm
from .models import ConfigConto, CoordinateBancarie, Distinta, VoceDistinta


def _errori(e):
    return " ".join(e.messages)


def _distinta(request, pk):
    return get_object_or_404(queryset(request, Distinta), pk=pk)


def _dettaglio(distinta):
    return redirect("distinte:distinte_dettaglio", distinta.pk)


@login_required
@permission_required("distinte.add_distinta", raise_exception=True)
def nuova(request):
    dati = request.POST if request.method == "POST" else (request.GET if "tipo" in request.GET else None)
    form = NuovaForm(request, dati)
    candidati = []
    if dati is not None and form.is_valid():
        tipo = form.cleaned_data["tipo"]
        candidati = servizi.candidati(request.azienda, tipo)
        if request.method == "POST":
            try:
                distinta = servizi.crea(request.azienda, tipo, form.cleaned_data["conto"], form.cleaned_data["data"],
                                        request.POST.getlist("scelte"), request.user)
            except ValidationError as e:
                messages.error(request, _errori(e))
            else:
                messages.success(request, f"Distinta creata con {distinta.voci.count()} voci: scarica il file e caricalo nella banca.")
                return _dettaglio(distinta)
    elif dati is None and len(form.fields["conto"].queryset) == 1:
        form.initial["conto"] = form.fields["conto"].queryset.first().pk
    return render(request, "distinte/nuova.html", {
        "form": form, "candidati": candidati, "scelte": set(request.POST.getlist("scelte")),
        "senza_conti": not form.fields["conto"].queryset.exists(),
        "totale": sum((c.importo for c in candidati if c.modalita_giusta and not c.problema), 0)})


@login_required
@permission_required("distinte.view_distinta", raise_exception=True)
def scarica(request, pk):
    distinta = _distinta(request, pk)
    try:
        nome, contenuto, tipo = servizi.file(distinta)
    except ValidationError as e:
        messages.error(request, _errori(e))
        return _dettaglio(distinta)
    risposta = HttpResponse(contenuto, content_type=tipo)
    risposta["Content-Disposition"] = f'attachment; filename="{nome}"'
    return risposta


@login_required
@permission_required("distinte.change_distinta", raise_exception=True)
@require_POST
def presenta(request, pk):
    distinta = _distinta(request, pk)
    servizi.presenta(distinta)
    messages.success(request, "Distinta segnata come presentata: quando la banca dà gli esiti, segnali qui.")
    return _dettaglio(distinta)


def _data(valore):
    try:
        return datetime.date.fromisoformat(valore) if valore else None
    except ValueError:
        return None


@login_required
@permission_required("distinte.change_distinta", raise_exception=True)
@require_POST
def esiti(request, pk):
    distinta = _distinta(request, pk)
    if distinta.attiva and not request.user.has_perm("fatturazione.add_incasso"):
        messages.error(request, "Per registrare gli incassi serve il permesso sugli incassi di Fatturazione.")
        return _dettaglio(distinta)
    azione, data = request.POST.get("azione"), _data(request.POST.get("data"))
    try:
        if azione == "tutte":
            n = servizi.tutte_pagate(distinta, data, request.user)
            messages.success(request, f"Voci segnate come pagate: {n}." + (" Gli incassi sono registrati sulle fatture." if distinta.attiva else ""))
        else:
            voce = get_object_or_404(VoceDistinta, pk=request.POST.get("voce"), distinta=distinta)
            if azione == "pagata":
                servizi.pagata(voce, data, request.user)
                messages.success(request, f"{voce.nome}: pagata.")
            elif azione == "insoluta":
                servizi.insoluta(voce, data, request.POST.get("motivo", ""))
                messages.success(request, f"{voce.nome}: insoluta, la scadenza torna aperta.")
    except ValidationError as e:
        messages.error(request, _errori(e))
    return _dettaglio(distinta)


@login_required
@permission_required("distinte.change_configconto", raise_exception=True)
@require_POST
def config_conto(request, pk):
    conto = get_object_or_404(queryset(request, Conto), pk=pk)
    form = ConfigContoForm(request.POST, instance=ConfigConto.objects.filter(conto=conto).first() or ConfigConto(conto=conto))
    if form.is_valid():
        form.save()
        messages.success(request, "Impostazioni delle distinte salvate.")
    else:
        messages.error(request, " ".join(e for errori in form.errors.values() for e in errori))
    return redirect("banca:conti_dettaglio", conto.pk)


@login_required
@permission_required("distinte.change_coordinatebancarie", raise_exception=True)
@require_POST
def coordinate(request, pk):
    contatto = get_object_or_404(queryset(request, Contatto), pk=pk)
    esistenti = CoordinateBancarie.objects.filter(contatto=contatto).first()
    if not request.POST.get("iban", "").strip() and esistenti:
        esistenti.delete()
        messages.success(request, "Coordinate bancarie tolte.")
        return redirect("contatti:contatti_dettaglio", contatto.pk)
    form = CoordinateForm(request.POST, instance=esistenti or CoordinateBancarie(contatto=contatto))
    if form.is_valid():
        form.save()
        messages.success(request, "Coordinate bancarie salvate.")
    else:
        messages.error(request, " ".join(e for errori in form.errors.values() for e in errori))
    return redirect("contatti:contatti_dettaglio", contatto.pk)
