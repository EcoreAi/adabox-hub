"""Il modulo del servizio: la chiave si scrive qui, si salva cifrata e non si rilegge più."""
from django import forms

from core import cifratura


class ServizioForm(forms.Form):
    nuova_chiave = forms.CharField(label="Nuova chiave", required=False, strip=True,
                                   widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
                                   help_text="La chiave d'accesso al servizio, se ne richiede una. Lascia vuoto per non cambiarla.")
    togli_chiave = forms.BooleanField(label="Togli la chiave", required=False)

    def salva(self, servizio):
        if self.cleaned_data.get("togli_chiave"):
            servizio.chiave_cifrata = ""
        elif self.cleaned_data.get("nuova_chiave"):
            servizio.chiave_cifrata = cifratura.cifra(self.cleaned_data["nuova_chiave"])
        else:
            return
        servizio.save()
