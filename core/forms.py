from django import forms
from django.contrib.auth.models import User

from .models import CampoPersonalizzato, ProfiloUtente, TokenApi


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


class CampoPersonalizzatoForm(forms.ModelForm):
    """Il modello si sceglie solo tra quelli che accettano campi personalizzati."""
    class Meta:
        model = CampoPersonalizzato
        fields = ["modello", "label", "nome", "tipo", "scelte", "aiuto", "obbligatorio", "in_lista", "filtrabile",
                  "ordine", "azienda"]

    def __init__(self, *args, **kwargs):
        from django.apps import apps
        from django.contrib.contenttypes.models import ContentType

        from . import proprieta
        super().__init__(*args, **kwargs)
        modelli = [m for m in apps.get_models() if proprieta.accetta(m)]
        self.fields["modello"].queryset = ContentType.objects.filter(
            pk__in=[ContentType.objects.get_for_model(m).pk for m in modelli])
