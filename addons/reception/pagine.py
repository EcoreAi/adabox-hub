"""Il chiosco: una pagina per il tablet all'ingresso, aperta con un utente che può solo registrare visite.
Si entra (nome, azienda, chi si incontra, informativa) e si esce toccando il proprio nome. La lista mostra solo nome e
iniziale del cognome. «Presenti ora» è la lista completa, da stampare per un'evacuazione."""
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import parametri

from . import servizi


def _colleghi(azienda):
    return (get_user_model().objects.filter(is_active=True, profilo__aziende=azienda).exclude(profilo__esterno=True)
            .order_by("first_name", "last_name", "username"))


class EntrataForm(forms.Form):
    nome = forms.CharField(label="Nome e cognome", max_length=120)
    societa = forms.CharField(label="Azienda", max_length=120, required=False)
    ospite = forms.ModelChoiceField(label="Chi incontri", queryset=get_user_model().objects.none(), required=False,
                                    empty_label="Non lo so / la reception")
    motivo = forms.CharField(label="Motivo", max_length=200, required=False)
    privacy = forms.BooleanField(label="Ho letto l'informativa sulla privacy")

    def __init__(self, *args, azienda=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ospite"].queryset = _colleghi(azienda)
        self.fields["ospite"].label_from_instance = lambda u: u.get_full_name() or u.username
        for nome, campo in self.fields.items():
            campo.widget.attrs.setdefault("class", "ui-input" if nome != "privacy" else "")
        self.fields["nome"].widget.attrs.update(autocomplete="off", autofocus=True)


@login_required
@permission_required("reception.add_visita", raise_exception=True)
def chiosco(request):
    if request.azienda is None:
        raise Http404
    form = EntrataForm(request.POST or None, azienda=request.azienda)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        v = servizi.entra(request.azienda, d["nome"], d["societa"], d["ospite"], d["motivo"])
        chi = d["ospite"].get_full_name() or d["ospite"].username if d["ospite"] else "La reception"
        messages.success(request, f"Benvenuto, {v.nome.split()[0]}! {chi} sa che sei arrivato.")
        return redirect("reception:chiosco")
    return render(request, "reception/chiosco.html", {
        "form": form, "presenti": servizi.presenti(request.azienda),
        "informativa": parametri.leggi("reception.informativa", request.azienda)})


@login_required
@permission_required("reception.add_visita", raise_exception=True)
@require_POST
def chiosco_uscita(request, pk):
    v = get_object_or_404(servizi.presenti(request.azienda), pk=pk)
    servizi.esce(v)
    messages.success(request, f"Arrivederci, {v.nome.split()[0]}!")
    return redirect("reception:chiosco")


@login_required
@permission_required("reception.view_visita", raise_exception=True)
def presenti(request):
    if request.azienda is None:
        raise Http404
    return render(request, "reception/presenti.html", {"presenti": servizi.presenti(request.azienda),
                                                       "attese": servizi.attese_oggi(request.azienda), "ora": timezone.now()})
