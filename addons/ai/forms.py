from django import forms

from core import cifratura

from .models import ChiaveAzienda, Provider


class ProviderForm(forms.ModelForm):
    """La chiave si scrive qui e si salva cifrata; vuota = resta quella di prima."""
    nuova_chiave = forms.CharField(label="chiave API", required=False, strip=True,
                                   widget=forms.PasswordInput(render_value=False, attrs={
                                       "autocomplete": "new-password", "data-lpignore": "true", "data-1p-ignore": "true",
                                       "spellcheck": "false"}),
                                   help_text="lascia vuoto per non cambiarla")
    togli_chiave = forms.BooleanField(label="togli la chiave", required=False)
    base_url = forms.URLField(label="URL dell'API", required=False, assume_scheme="https",
                              widget=forms.URLInput(attrs={"autocomplete": "off"}),
                              help_text="per Anthropic lascia vuoto; per Ollama/OpenRouter l'indirizzo dell'API")

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

    def clean(self):
        """Per Anthropic: niente URL locali e chiavi che non sono chiavi (tipico del compilatore automatico del
        browser, che mette la password del login nel campo della chiave)."""
        from urllib.parse import urlparse
        dati = super().clean()
        if dati.get("tipo") == Provider.ANTHROPIC:
            host = urlparse(dati.get("base_url") or "").hostname or ""
            if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.startswith("192.168."):
                self.add_error("base_url", "Per Anthropic lascia vuoto l'URL: si usa api.anthropic.com.")
            chiave = dati.get("nuova_chiave") or ""
            if chiave and not chiave.startswith("sk-ant-"):
                self.add_error("nuova_chiave", "Non sembra una chiave API Anthropic (inizia con «sk-ant-»). "
                                               "Forse il browser ha inserito da solo la password del login.")
        return dati

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
                             widget=forms.PasswordInput(render_value=False, attrs={
                                 "autocomplete": "new-password", "data-lpignore": "true", "data-1p-ignore": "true"}))

    def clean(self):
        dati = super().clean()
        provider, chiave = dati.get("provider"), dati.get("chiave") or ""
        if provider and provider.tipo == Provider.ANTHROPIC and chiave and not chiave.startswith("sk-ant-"):
            self.add_error("chiave", "Non sembra una chiave API Anthropic (inizia con «sk-ant-»).")
        return dati

    class Meta:
        model = ChiaveAzienda
        fields = ["provider", "azienda"]

    def save(self, commit=True):
        riga = super().save(commit=False)
        riga.chiave_cifrata = cifratura.cifra(self.cleaned_data["chiave"])
        if commit:
            riga.save()
        return riga
