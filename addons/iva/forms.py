from django import forms

from .models import Detraibilita, Liquidazione


class ManualiForm(forms.ModelForm):
    """Le voci che non stanno nei registri: crediti usati in compensazione, acconto di dicembre, note."""

    class Meta:
        model = Liquidazione
        fields = ["credito_anno_precedente", "crediti_imposta", "versamenti_auto", "acconto", "metodo_acconto", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}


class DetraibilitaForm(forms.ModelForm):
    class Meta:
        model = Detraibilita
        fields = ["percentuale", "motivo"]
