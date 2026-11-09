from django import forms

from core import cifratura
from core.viste import ModelView, register

from .models import Aggregatore, CollegamentoConto, Conto, MovimentoBanca


@register
class ContoView(ModelView):
    model = Conto
    slug = "conti"
    list_display = ["nome", "iban", "banca", "saldo", "saldo_al", "attivo"]
    list_filter = ["attivo"]
    search_fields = ["nome", "iban", "banca"]
    form_layout = [("Conto", [("nome", "banca"), ("iban", "bic"), "attivo"])]
    readonly_fields = ["saldo", "saldo_al"]
    company_field = "azienda"


@register
class MovimentoView(ModelView):
    """I movimenti arrivano dalla banca: si guardano e si abbinano, non si scrivono a mano."""
    model = MovimentoBanca
    slug = "movimenti"
    list_display = ["data", "conto", "importo", "controparte", "descrizione", "stato"]
    list_filter = ["stato", "conto", "data"]
    search_fields = ["descrizione", "controparte", "riferimento", "iban_controparte"]
    form_layout = [("MovimentoBanca", [("data", "valuta"), ("conto", "importo"), ("controparte", "iban_controparte"), "riferimento", "descrizione"])]
    readonly_fields = ["data", "valuta", "conto", "importo", "controparte", "iban_controparte", "riferimento", "descrizione", "stato"]
    company_field = "azienda"
    list_sum = ["importo"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False if obj is not None else super().has_change_permission(request, obj)

    def col_descrizione(self, obj):
        return obj.descrizione[:80] + ("…" if len(obj.descrizione) > 80 else "")
    col_descrizione.short_description = "Descrizione"


class AggregatoreForm(forms.ModelForm):
    """La Secret Key si scrive qui, si salva cifrata e non si rilegge."""
    nuova_chiave = forms.CharField(label="Secret Key", required=False, strip=True,
                                   widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
                                   help_text="Dal portale di GoCardless Bank Account Data, in User secrets; vuota per non cambiarla")

    class Meta:
        model = Aggregatore
        fields = ["nome", "tipo", "secret_id", "attivo"]

    def clean(self):
        dati = super().clean()
        if dati.get("tipo") == Aggregatore.GOCARDLESS:
            if not dati.get("secret_id"):
                self.add_error("secret_id", "Serve il Secret ID.")
            if not dati.get("nuova_chiave") and not self.instance.secret_key_cifrata:
                self.add_error("nuova_chiave", "Serve la Secret Key.")
        return dati

    def save(self, commit=True):
        if self.cleaned_data.get("nuova_chiave"):
            self.instance.secret_key_cifrata = cifratura.cifra(self.cleaned_data["nuova_chiave"])
        return super().save(commit)


@register
class AggregatoreView(ModelView):
    """Il servizio PSD2 con cui i conti si leggono in automatico. Si usa il primo attivo."""
    model = Aggregatore
    api = False                   # contiene segreti o credenziali: niente API
    slug = "aggregatori"
    company_field = "azienda"
    list_display = ["nome", "tipo", "secret_id", "attivo"]
    form_class = AggregatoreForm
    form_layout = [("Servizio", [("nome", "tipo"), "secret_id", "nuova_chiave", "attivo"])]
    buttons = ["prova"]
    ai_descrizione = "Il servizio di lettura automatica dei conti bancari (PSD2)."

    def layout_dettaglio(self):
        return [(t, [[c for c in riga if c != "nuova_chiave"] for riga in righe if any(c != "nuova_chiave" for c in riga)])
                for t, righe in super().layout_dettaglio()]

    def prova(self, request, obj):
        from . import sincronia
        try:
            n = len(sincronia.banche(obj))
        except sincronia.ErroreBanca as e:
            return f"Prova non riuscita: {e}"
        return f"Il servizio risponde: {n} banche italiane disponibili."
    prova.short_description = "Prova le chiavi"
    prova.ai = False


@register
class CollegamentoView(ModelView):
    """I conti letti in automatico: si collegano dalla scheda del conto."""
    model = CollegamentoConto
    slug = "collegamenti"
    company_field = "azienda"
    list_display = ["conto", "nome_istituto", "stato", "scade_il", "ultima_lettura", "errore"]
    list_filter = ["stato"]
    readonly_fields = ["conto", "aggregatore", "istituto", "nome_istituto", "richiesta", "link_consenso", "conto_esterno", "stato",
                       "scade_il", "giorni_storico", "ultima_lettura", "letto_fino_al", "errore", "utente", "creato"]
    form_layout = [("CollegamentoConto", [("conto", "nome_istituto"), ("stato", "scade_il"), ("ultima_lettura", "letto_fino_al"), "errore",
                                     ("aggregatore", "utente")])]
    ai_descrizione = "I conti bancari collegati per la lettura automatica: banca, stato del consenso e ultima lettura."

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False if obj is not None else super().has_change_permission(request, obj)
