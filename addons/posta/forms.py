"""Il modulo del servizio: il segreto si scrive qui, si salva cifrato e non si rilegge più."""
from django import forms

from core import cifratura

from .models import ServizioOAuth


class ServizioForm(forms.ModelForm):
    nuovo_segreto = forms.CharField(label="Segreto client", required=False, strip=True,
                                    widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}))

    class Meta:
        model = ServizioOAuth
        fields = ["tipo", "client_id", "tenant", "attivo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nuovo_segreto"].help_text = ("Già inserito: lascia vuoto per non cambiarlo." if self.instance.pk and self.instance.segreto_cifrato
                                                  else "Google Cloud: Credenziali, ID client OAuth «Applicazione web». "
                                                       "Microsoft Entra: Registrazioni app, Certificati e segreti.")

    def clean(self):
        dati = super().clean()
        if not dati.get("nuovo_segreto") and not self.instance.segreto_cifrato:
            self.add_error("nuovo_segreto", "Serve il segreto client.")
        return dati

    def save(self, commit=True):
        if self.cleaned_data.get("nuovo_segreto"):
            self.instance.segreto_cifrato = cifratura.cifra(self.cleaned_data["nuovo_segreto"])
        return super().save(commit)
