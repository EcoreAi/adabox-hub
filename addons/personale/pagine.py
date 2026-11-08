"""Le mie assenze: saldo, richieste fatte e una nuova richiesta, per il dipendente collegato all'utente."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.viste import registry

from . import flusso, organigramma as org, saldi
from .models import Assenza, Dipendente, Reparto, TipoAssenza


class RichiestaForm(forms.ModelForm):
    class Meta:
        model = Assenza
        fields = ["tipo", "dal", "al", "ore", "motivo"]
        widgets = {"dal": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "al": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, dipendente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.dipendente, self.instance.azienda = dipendente, dipendente.azienda
        self.fields["tipo"].queryset = TipoAssenza.objects.filter(attivo=True)
        for campo in self.fields.values():
            campo.widget.attrs.setdefault("class", "ui-input")


@login_required
@permission_required("personale.add_assenza", raise_exception=True)
def mie(request):
    dipendente = Dipendente.objects.filter(utente=request.user, attivo=True).select_related("azienda").first()
    if dipendente is None:
        return render(request, "personale/mie.html", {"dipendente": None})
    form = RichiestaForm(request.POST or None, dipendente=dipendente)
    if request.method == "POST" and form.is_valid():
        assenza = form.save()
        flusso.richiesta_inviata(assenza, request.user)
        messages.success(request, f"Richiesta inviata: {assenza}." + (
            "" if dipendente.approvatori() else " Nessun responsabile indicato: la vedrà l'ufficio del personale."))
        return redirect("personale:mie")
    anno = timezone.localdate().year
    return render(request, "personale/mie.html", {
        "dipendente": dipendente, "form": form, "saldo": saldi.saldo(dipendente, anno), "anno": anno,
        "assenze": dipendente.assenze.select_related("tipo")[:30],
        "da_approvare": Assenza.objects.filter(stato=Assenza.RICHIESTA, dipendente__responsabile=dipendente).count()})


@login_required
@permission_required("personale.view_dipendente", raise_exception=True)
def organigramma(request):
    """L'organigramma dell'azienda corrente (o di un reparto), dai responsabili; a lato le posizioni scoperte."""
    vista = registry.per_modello(Dipendente)
    persone = (vista.get_queryset(request).filter(attivo=True)
               .select_related("posizione", "reparto", "utente"))
    reparti = Reparto.objects.filter(azienda=request.azienda).order_by("nome") if request.azienda else Reparto.objects.none()
    reparto = None
    if request.GET.get("reparto", "").isdigit():
        reparto = get_object_or_404(reparti, pk=request.GET["reparto"])
        persone = persone.filter(reparto=reparto)
    persone = list(persone)
    radici = org.albero(persone)

    def link(nodi):
        for n in nodi:
            n.url = vista.url("dettaglio", pk=n.dipendente.pk)
            link(n.figli)
    link(radici)
    return render(request, "personale/organigramma.html", {
        "radici": radici, "totale": len(persone), "reparti": reparti, "reparto": reparto,
        "scoperte": org.scoperte(request.azienda, reparto) if request.azienda else []})
