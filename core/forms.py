from django import forms
from django.contrib.auth.models import User

from .models import ProfiloUtente, TokenApi


class ProfiloForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {"first_name": "Nome", "last_name": "Cognome", "email": "Email"}
        widgets = {f: forms.TextInput(attrs={"class": "ui-input"}) for f in ["first_name", "last_name"]}
        widgets["email"] = forms.EmailInput(attrs={"class": "ui-input"})


class TokenApiForm(forms.ModelForm):
    class Meta:
        model = TokenApi
        fields = ["nome"]
        labels = {"nome": "Nome del token"}
        widgets = {"nome": forms.TextInput(attrs={"class": "ui-input", "placeholder": "es. integrazione adabox"})}


class AziendaPredefinitaForm(forms.ModelForm):
    """Azienda proposta all'apertura della sessione: solo tra quelle consentite e attive."""
    class Meta:
        model = ProfiloUtente
        fields = ["azienda_predefinita"]
        widgets = {"azienda_predefinita": forms.Select(attrs={"class": "ui-input"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["azienda_predefinita"]
        campo.queryset = self.instance.aziende.filter(attiva=True)
        campo.required = True
        campo.empty_label = None
