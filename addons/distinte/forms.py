import datetime

from django import forms

from core.dashboard import queryset
from banca.models import Conto

from .models import ConfigConto, CoordinateBancarie, Distinta


class NuovaForm(forms.Form):
    tipo = forms.ChoiceField(label="Tipo", choices=Distinta.TIPI)
    conto = forms.ModelChoiceField(label="Conto", queryset=Conto.objects.none())
    data = forms.DateField(label="Data", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                           help_text="esecuzione dei bonifici o addebito SDD; per le RiBa la data di presentazione")

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["conto"].queryset = queryset(request, Conto).filter(attivo=True)
        if not self.is_bound:
            self.initial.setdefault("data", datetime.date.today() + datetime.timedelta(days=2))


class ConfigContoForm(forms.ModelForm):
    class Meta:
        model = ConfigConto
        fields = ["codice_sia", "id_creditore", "versione_sepa"]


class CoordinateForm(forms.ModelForm):
    class Meta:
        model = CoordinateBancarie
        fields = ["iban", "bic", "banca"]
