"""Il modulo del collegamento: il token si scrive qui, si salva cifrato e non si rilegge più."""
from django import forms

from core import cifratura

from .models import CollegamentoEsterno, RiferimentoEsterno


class CollegamentoForm(forms.ModelForm):
    nuovo_token = forms.CharField(label="Token dell'app privata", required=False, strip=True,
                                  widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}))

    class Meta:
        model = CollegamentoEsterno
        fields = ["sistema", "modalita", "comanda", "aziende", "opportunita", "attivo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nuovo_token"].help_text = ("Già inserito: lascia vuoto per non cambiarlo." if self.instance.pk and self.instance.token_cifrato
                                                else "In HubSpot: Impostazioni, Integrazioni, App private; servono gli ambiti di lettura e scrittura di "
                                                     "contatti, aziende e trattative (crm.objects.contacts, companies, deals).")

    def clean(self):
        dati = super().clean()
        if dati.get("modalita") == CollegamentoEsterno.VERA and not dati.get("nuovo_token") and not self.instance.token_cifrato:
            self.add_error("nuovo_token", "Per un collegamento vero serve il token.")
        return dati

    def save(self, commit=True):
        i = self.instance
        if i.pk and "modalita" in self.changed_data:       # i dati di prova non valgono per il sistema vero, e viceversa
            i.cursore = None
            RiferimentoEsterno.objects.filter(azienda_id=i.azienda_id, sistema=i.sistema).delete()
        if self.cleaned_data.get("nuovo_token"):
            i.token_cifrato = cifratura.cifra(self.cleaned_data["nuovo_token"])
        return super().save(commit)
