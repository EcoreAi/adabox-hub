from django import forms

from core import cifratura

from .models import FornitorePagamento


class FornitoreForm(forms.ModelForm):
    """Le chiavi si scrivono qui, si salvano cifrate e non si rileggono."""
    nuova_chiave = forms.CharField(label="chiave segreta", required=False, strip=True,
                                   widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
                                   help_text="Stripe: sk_test_… per le prove, sk_live_… per incassare davvero; vuota per non cambiarla")
    nuovo_segreto = forms.CharField(label="segreto dei webhook", required=False, strip=True,
                                    widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
                                    help_text="whsec_… dall'endpoint webhook creato su Stripe; vuoto per non cambiarlo")

    class Meta:
        model = FornitorePagamento
        fields = ["nome", "tipo", "attivo"]

    def clean(self):
        dati = super().clean()
        chiave = dati.get("nuova_chiave") or ""
        if dati.get("tipo") == FornitorePagamento.STRIPE:
            if chiave and not chiave.startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_")):
                self.add_error("nuova_chiave", "La chiave segreta di Stripe inizia con sk_test_ o sk_live_.")
            if not chiave and not self.instance.chiave_cifrata:
                self.add_error("nuova_chiave", "Per Stripe serve la chiave segreta.")
        return dati

    def save(self, commit=True):
        if self.cleaned_data.get("nuova_chiave"):
            self.instance.chiave_cifrata = cifratura.cifra(self.cleaned_data["nuova_chiave"])
        if self.cleaned_data.get("nuovo_segreto"):
            self.instance.segreto_webhook_cifrato = cifratura.cifra(self.cleaned_data["nuovo_segreto"])
        return super().save(commit)
