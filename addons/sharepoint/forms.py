"""Il modulo del collegamento: il client secret si scrive qui, si salva cifrato e non si rilegge più."""
from django import forms
from django.db.models import Q

from core import cifratura

from . import graph
from .models import CollegamentoSharePoint, FileProva, FileSharePoint

AIUTO_SEGRETO = ("Il valore (non l'ID) di un client secret dell'app registrata in Microsoft Entra ID → Registrazioni app → "
                 "Certificati e segreti. All'app servono i permessi applicativi di Microsoft Graph Sites.Selected, con "
                 "l'accesso concesso al solo sito, oppure Sites.ReadWrite.All.")


def _antenate(cartella):
    visti, c = set(), cartella
    while c is not None and c.pk not in visti:
        visti.add(c.pk)
        c = c.padre
    return visti


class CollegamentoForm(forms.ModelForm):
    nuovo_segreto = forms.CharField(label="Client secret", required=False, strip=True,
                                    widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}))

    class Meta:
        model = CollegamentoSharePoint
        fields = ["nome", "cartella", "verso", "modalita", "attivo", "sito", "libreria", "percorso", "tenant", "client_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "cartella" in self.fields:                   # gli spazi personali restano dei loro proprietari
            self.fields["cartella"].queryset = self.fields["cartella"].queryset.filter(
                Q(spazio__isnull=True) | Q(spazio__tipo="condiviso"))
        gia = self.instance.pk and self.instance.segreto_cifrato
        self.fields["nuovo_segreto"].help_text = "Già inserito: lascia vuoto per non cambiarlo." if gia else AIUTO_SEGRETO

    def clean_percorso(self):
        try:
            return graph.percorso_pulito(self.cleaned_data.get("percorso"))
        except graph.ErroreSharePoint as e:
            raise forms.ValidationError(str(e)) from e

    def clean(self):
        dati = super().clean()
        cartella = dati.get("cartella")
        if cartella is not None:
            self._controlla_sovrapposizioni(cartella)
        if dati.get("modalita") != CollegamentoSharePoint.VERA:
            return dati
        for campo, valida in (("sito", graph.sito_valido), ("tenant", graph.tenant_valido)):
            try:
                dati[campo] = valida(dati.get(campo))
            except graph.ErroreSharePoint as e:
                self.add_error(campo, str(e))
        if not (dati.get("client_id") or "").strip():
            self.add_error("client_id", "Serve il client id dell'app registrata in Microsoft Entra ID.")
        if not (dati.get("nuovo_segreto") or self.instance.segreto_cifrato):
            self.add_error("nuovo_segreto", "Serve il client secret.")
        return dati

    def _controlla_sovrapposizioni(self, cartella):
        """Una cartella sta in un solo collegamento, anche come sottocartella: due giri sugli stessi documenti si
        rincorrerebbero."""
        altri = CollegamentoSharePoint.objects.filter(azienda_id=cartella.azienda_id).exclude(pk=self.instance.pk).select_related("cartella")
        antenate = _antenate(cartella)
        for altro in altri:
            if altro.cartella_id in antenate:
                self.add_error("cartella", f"Questa cartella è già dentro al collegamento «{altro}».")
                return
            if cartella.pk in _antenate(altro.cartella):
                self.add_error("cartella", f"Questa cartella contiene quella del collegamento «{altro}».")
                return

    def save(self, commit=True):
        i, cambiati = self.instance, set(self.changed_data)
        if i.pk and {"modalita", "sito", "libreria", "percorso", "cartella"} & cambiati:
            FileSharePoint.objects.filter(collegamento=i).delete()           # altri file, altra corrispondenza
            i.drive_id = i.cartella_id_esterna = ""
            if "modalita" in cambiati:
                FileProva.objects.filter(collegamento=i).delete()
        if {"modalita", "tenant", "client_id"} & cambiati or self.cleaned_data.get("nuovo_segreto"):
            i.accesso_cifrato, i.accesso_scade = "", None
        if self.cleaned_data.get("nuovo_segreto"):
            i.segreto_cifrato = cifratura.cifra(self.cleaned_data["nuovo_segreto"])
        return super().save(commit)
