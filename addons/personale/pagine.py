"""Le mie assenze: saldo, richieste fatte e una nuova richiesta, per il dipendente collegato all'utente."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render
from django.utils import timezone

from . import flusso, saldi
from .models import Assenza, Dipendente, TipoAssenza


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
