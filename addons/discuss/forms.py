"""Moduli che non bastano da soli: i segreti si scrivono qui, si salvano cifrati e non si rileggono più."""
from django import forms

from core import cifratura

from .models import Connessione


def _segreto(etichetta):
    return forms.CharField(label=etichetta, required=False, strip=True, widget=forms.PasswordInput(render_value=False, attrs={
        "autocomplete": "new-password", "data-lpignore": "true", "data-1p-ignore": "true", "spellcheck": "false"}))


class ConnessioneForm(forms.ModelForm):
    nuovo_token = _segreto("Token")
    nuovo_segreto = _segreto("Chiave segreta dell'app (solo WhatsApp)")

    class Meta:
        model = Connessione
        fields = ["nome", "tipo", "sportello", "sandbox", "attiva", "id_numero", "id_account"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        i = self.instance
        self.fields["nuovo_token"].help_text = ("Già inserito: lascia vuoto per non cambiarlo." if i.pk and i.token_cifrato
                                                else "WhatsApp: token di accesso di Meta. Telegram: token di @BotFather.")
        self.fields["nuovo_segreto"].help_text = "Con questa si controlla che i messaggi vengano davvero da Meta."

    def clean(self):
        """Una connessione vera senza credenziali non funzionerebbe, e lo si dice adesso, non al primo cliente."""
        dati = super().clean()
        if dati.get("sandbox"):
            return dati
        if not dati.get("nuovo_token") and not self.instance.token_cifrato:
            self.add_error("nuovo_token", "Per una connessione vera serve il token.")
        if dati.get("tipo") == Connessione.WHATSAPP:
            if not dati.get("id_numero"):
                self.add_error("id_numero", "WhatsApp ha bisogno dell'ID del numero.")
            # da prova a vera il segreto generato non vale: quello buono lo dà Meta
            gia_vera = self.instance.pk and not self.instance.sandbox
            if not dati.get("nuovo_segreto") and not gia_vera:
                self.add_error("nuovo_segreto", "WhatsApp ha bisogno della chiave segreta dell'app.")
        return dati

    def save(self, commit=True):
        c = super().save(commit=False)
        if self.cleaned_data.get("nuovo_token"):
            c.token_cifrato = cifratura.cifra(self.cleaned_data["nuovo_token"])
        if self.cleaned_data.get("nuovo_segreto"):
            c.segreto_cifrato = cifratura.cifra(self.cleaned_data["nuovo_segreto"])
        if commit:
            c.save()
        return c
