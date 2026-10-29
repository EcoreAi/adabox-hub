from django import forms

from core import cifratura

from .models import ChiaveAzienda, Provider


class ProviderForm(forms.ModelForm):
    """La chiave si scrive qui e si salva cifrata; vuota = resta quella di prima."""
    nuova_chiave = forms.CharField(label="chiave API", required=False, strip=True,
                                   widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"}),
                                   help_text="lascia vuoto per non cambiarla")
    togli_chiave = forms.BooleanField(label="togli la chiave", required=False)
    base_url = forms.URLField(label="URL dell'API", required=False, assume_scheme="https",
                              help_text="vuoto = quello predefinito del tipo")

    class Meta:
        model = Provider
        fields = ["nome", "tipo", "base_url", "locale", "attivo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.chiave_cifrata:
            try:
                attuale = cifratura.mascherato(cifratura.decifra(self.instance.chiave_cifrata))
            except cifratura.SegretoIlleggibile:
                attuale = "illeggibile: inseriscila di nuovo"
            self.fields["nuova_chiave"].help_text = f"attuale: {attuale}; lascia vuoto per non cambiarla"

    def save(self, commit=True):
        provider = super().save(commit=False)
        if self.cleaned_data.get("togli_chiave"):
            provider.chiave_cifrata = ""
        elif self.cleaned_data.get("nuova_chiave"):
            provider.chiave_cifrata = cifratura.cifra(self.cleaned_data["nuova_chiave"])
        if commit:
            provider.save()
        return provider


class ChiaveAziendaForm(forms.ModelForm):
    chiave = forms.CharField(label="chiave API", strip=True,
                             widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"}))

    class Meta:
        model = ChiaveAzienda
        fields = ["provider", "azienda"]

    def save(self, commit=True):
        riga = super().save(commit=False)
        riga.chiave_cifrata = cifratura.cifra(self.cleaned_data["chiave"])
        if commit:
            riga.save()
        return riga
