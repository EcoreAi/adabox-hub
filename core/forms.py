import datetime

from django import forms
from django.utils import timezone
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
    DURATE = [("90", "90 giorni"), ("365", "1 anno"), ("30", "30 giorni"), ("7", "7 giorni"), ("", "Senza scadenza")]
    durata = forms.ChoiceField(label="Durata", choices=DURATE, required=False, initial="90", widget=forms.Select(attrs={"class": "ui-input"}))
    sola_lettura = forms.BooleanField(label="Sola lettura", required=False, initial=True)
    moduli = forms.MultipleChoiceField(label="Solo questi moduli (nessuna scelta = tutti)", required=False, widget=forms.SelectMultiple(attrs={"class": "ui-input", "size": 4}))

    def __init__(self, *args, utente=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .registry import modules
        self.fields["moduli"].choices = [(a["slug"], a["label"]) for a in modules.app_visibili(utente)] if utente else []

    def scadenza(self):
        giorni = self.cleaned_data.get("durata")
        return timezone.localdate() + datetime.timedelta(days=int(giorni)) if giorni else None

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
        fields = ["modello", "label", "nome", "tipo", "scelte", "collega_a", "aiuto", "obbligatorio", "in_lista", "filtrabile",
                  "ordine", "azienda"]

    def __init__(self, *args, **kwargs):
        from django.apps import apps
        from django.contrib.contenttypes.models import ContentType

        from . import proprieta
        super().__init__(*args, **kwargs)
        modelli = [m for m in apps.get_models() if proprieta.accetta(m)]
        self.fields["modello"].queryset = ContentType.objects.filter(
            pk__in=[ContentType.objects.get_for_model(m).pk for m in modelli])
        from .viste import registry
        con_vista = {v.model for vv in registry._viste.values() for v in vv}
        self.fields["collega_a"].queryset = ContentType.objects.filter(
            pk__in=[ContentType.objects.get_for_model(m).pk for m in con_vista]).order_by("app_label", "model")

    def clean(self):
        dati = super().clean()
        if dati.get("tipo") == CampoPersonalizzato.COLLEGAMENTO and not dati.get("collega_a"):
            self.add_error("collega_a", "Scegli a quale tipo di record si collega.")
        return dati
