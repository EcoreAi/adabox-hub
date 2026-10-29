from django import forms

from core import cifratura

from .models import Assistente, ChiaveAzienda, Pianificata, Provider


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


class PianificataForm(forms.ModelForm):
    """Giorni della settimana a caselle; i campi che servono dipendono da «quando»."""
    giorni = forms.TypedMultipleChoiceField(label="giorni della settimana", coerce=int, required=False,
                                            choices=Pianificata.GIORNI_SETTIMANA, widget=forms.CheckboxSelectMultiple)
    ambito = forms.ChoiceField(label="solo per l'app", required=False)

    class Meta:
        model = Pianificata
        fields = ["nome", "istruzioni", "ambito", "ricorrenza", "alle", "giorni", "giorno_mese", "ogni_ore",
                  "minuti_prima", "in_discuss", "per_email", "attiva"]
        widgets = {"alle": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "istruzioni": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        from core.registry import modules
        super().__init__(*args, **kwargs)
        self.fields["ambito"].choices = [("", "Tutte le app")] + [
            (slug, m.name) for slug, m in modules.manifests_attivi().items() if m.application and slug != "ai"]
        if self.instance.pk:
            self.initial["giorni"] = self.instance.elenco_giorni()

    def clean_giorni(self):
        return ",".join(str(g) for g in sorted(set(self.cleaned_data["giorni"])))

    def clean(self):
        dati = super().clean()
        quando = dati.get("ricorrenza")
        errori = {}
        if quando == Pianificata.GIORNI and not dati.get("giorni"):
            errori["giorni"] = "Scegli almeno un giorno."
        if quando == Pianificata.MESE and not 1 <= (dati.get("giorno_mese") or 0) <= 28:
            errori["giorno_mese"] = "Indica un giorno da 1 a 28."
        if quando == Pianificata.ORE and not 1 <= (dati.get("ogni_ore") or 0) <= 168:
            errori["ogni_ore"] = "Indica un numero di ore da 1 a 168."
        if quando == Pianificata.EVENTI and not 5 <= (dati.get("minuti_prima") or 0) <= 1440:
            errori["minuti_prima"] = "Indica da 5 a 1440 minuti."
        for campo, messaggio in errori.items():
            self.add_error(campo, messaggio)
        return dati


class AssistenteForm(forms.ModelForm):
    """Strumenti a caselle (tutti quelli registrati); app tra quelle installate."""
    strumenti = forms.MultipleChoiceField(label="strumenti ammessi", required=False, widget=forms.CheckboxSelectMultiple,
                                          help_text="nessuno spuntato = tutti quelli permessi all'utente")
    app = forms.ChoiceField(label="app", required=False)

    class Meta:
        model = Assistente
        fields = ["nome", "descrizione", "app", "predefinito", "istruzioni", "strumenti", "profilo", "gruppi",
                  "domande_oro", "attivo"]
        widgets = {"istruzioni": forms.Textarea(attrs={"rows": 6}), "domande_oro": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        from core.registry import modules

        from .strumenti import registro
        super().__init__(*args, **kwargs)
        self.fields["strumenti"].choices = [(n, n) for n in sorted(registro._registro)]
        self.fields["app"].choices = [("", "Generale (tutte le app)")] + [
            (slug, m.name) for slug, m in modules.manifests_attivi().items() if m.application and slug != "ai"]

    def clean(self):
        dati = super().clean()
        if dati.get("predefinito") and dati.get("app"):
            self.add_error("predefinito", "Solo un assistente generale (senza app) può essere il predefinito.")
        domande = dati.get("domande_oro") or []
        if not isinstance(domande, list) or not all(isinstance(d, dict) and d.get("domanda") for d in domande):
            self.add_error("domande_oro", 'Una lista di oggetti con almeno "domanda".')
        return dati
