from django import forms

from core import cifratura

from .models import ProviderAccesso


class ProviderAccessoForm(forms.ModelForm):
    """Il segreto si scrive qui e si salva cifrato; vuoto = resta quello di prima."""
    nuovo_segreto = forms.CharField(label="client secret", required=False, strip=True,
                                    widget=forms.PasswordInput(render_value=False, attrs={
                                        "autocomplete": "new-password", "data-lpignore": "true", "data-1p-ignore": "true"}),
                                    help_text="lascia vuoto per non cambiarlo")

    class Meta:
        model = ProviderAccesso
        fields = ["tipo", "client_id", "tenant", "attivo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.segreto_cifrato:
            try:
                attuale = cifratura.mascherato(cifratura.decifra(self.instance.segreto_cifrato))
            except cifratura.SegretoIlleggibile:
                attuale = "illeggibile: inseriscilo di nuovo"
            self.fields["nuovo_segreto"].help_text = f"attuale: {attuale}; lascia vuoto per non cambiarlo"

    def clean(self):
        dati = super().clean()
        if not self.instance.segreto_cifrato and not dati.get("nuovo_segreto"):
            self.add_error("nuovo_segreto", "Serve il client secret del servizio.")
        return dati

    def save(self, commit=True):
        if self.cleaned_data.get("nuovo_segreto"):
            self.instance.segreto_cifrato = cifratura.cifra(self.cleaned_data["nuovo_segreto"])
        return super().save(commit)
