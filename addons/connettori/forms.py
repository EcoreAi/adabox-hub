"""Il modulo del collegamento: token e segreti si scrivono qui, si salvano cifrati e non si rileggono più."""
from django import forms

from core import cifratura

from .models import CollegamentoEsterno, RiferimentoEsterno
from .sistemi.base import ErroreConnettore
from .sistemi.salesforce import dominio_valido
from .sistemi.zoho import centro_valido

AIUTO_TOKEN = ("HubSpot: il token dell'app privata (Impostazioni, Integrazioni, App private), con gli ambiti di lettura e scrittura di "
               "contatti, aziende e trattative. Zoho: il refresh token del Self Client (api-console.zoho.com).")
AIUTO_SEGRETO = "Salesforce: il consumer secret della Connected App. Zoho: il client secret del Self Client."


class CollegamentoForm(forms.ModelForm):
    nuovo_token = forms.CharField(label="Token o refresh token", required=False, strip=True,
                                  widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}))
    nuovo_segreto = forms.CharField(label="Client secret", required=False, strip=True,
                                    widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}))

    azienda_id = None                    # la vista lo fissa: serve a dire per tempo che il sistema è già collegato

    class Meta:
        model = CollegamentoEsterno
        fields = ["sistema", "modalita", "comanda", "aziende", "opportunita", "attivo", "indirizzo", "client_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        gia = "Già inserito: lascia vuoto per non cambiarlo."
        self.fields["nuovo_token"].help_text = gia if self.instance.pk and self.instance.token_cifrato else AIUTO_TOKEN
        self.fields["nuovo_segreto"].help_text = gia if self.instance.pk and self.instance.segreto_cifrato else AIUTO_SEGRETO

    def clean(self):
        dati = super().clean()
        azienda_id = self.instance.azienda_id or self.azienda_id
        if azienda_id and dati.get("sistema") and (CollegamentoEsterno.objects.filter(azienda_id=azienda_id, sistema=dati["sistema"])
                                                   .exclude(pk=self.instance.pk).exists()):
            self.add_error("sistema", "Questo sistema è già collegato: modifica il collegamento che c'è.")
        if dati.get("modalita") != CollegamentoEsterno.VERA:
            return dati
        sistema, i = dati.get("sistema"), self.instance
        stesso = i.pk and i.sistema == sistema                   # i segreti salvati valgono solo per lo stesso sistema
        token = dati.get("nuovo_token") or (stesso and i.token_cifrato)
        segreto = dati.get("nuovo_segreto") or (stesso and i.segreto_cifrato)
        if sistema == CollegamentoEsterno.HUBSPOT:
            if not token:
                self.add_error("nuovo_token", "Per un collegamento vero serve il token.")
            return dati
        if not dati.get("client_id"):
            self.add_error("client_id", "Serve il client id.")
        if not segreto:
            self.add_error("nuovo_segreto", "Serve il client secret.")
        try:
            dati["indirizzo"] = dominio_valido(dati.get("indirizzo")) if sistema == CollegamentoEsterno.SALESFORCE else centro_valido(dati.get("indirizzo"))
        except ErroreConnettore as e:
            self.add_error("indirizzo", str(e))
        if sistema == CollegamentoEsterno.ZOHO and not token:
            self.add_error("nuovo_token", "Serve il refresh token.")
        return dati

    def save(self, commit=True):
        i = self.instance
        if i.pk and {"modalita", "sistema"} & set(self.changed_data):     # i dati di prova non valgono per il sistema vero, e viceversa
            i.cursore, i.cursori, i.accesso_cifrato, i.accesso_scade = None, {}, "", None
            if "modalita" in self.changed_data:
                RiferimentoEsterno.objects.filter(azienda_id=i.azienda_id, sistema=i.sistema).delete()
            if "sistema" in self.changed_data:
                i.token_cifrato = i.segreto_cifrato = ""
        if {"indirizzo", "client_id"} & set(self.changed_data):
            i.accesso_cifrato, i.accesso_scade = "", None
        if self.cleaned_data.get("nuovo_token"):
            i.token_cifrato = cifratura.cifra(self.cleaned_data["nuovo_token"])
            i.accesso_cifrato, i.accesso_scade = "", None
        if self.cleaned_data.get("nuovo_segreto"):
            i.segreto_cifrato = cifratura.cifra(self.cleaned_data["nuovo_segreto"])
            i.accesso_cifrato, i.accesso_scade = "", None
        return super().save(commit)
