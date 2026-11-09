from core import cifratura
from core.viste import ModelView, register

from .forms import FornitoreForm
from .models import FornitorePagamento, Pagamento


@register
class FornitoreView(ModelView):
    """Il conto online dell'azienda. Si usa il primo fornitore attivo."""
    model = FornitorePagamento
    api = False                   # contiene segreti o credenziali: niente API
    slug = "fornitori"
    company_field = "azienda"
    list_display = ["nome", "tipo", "chiave", "attivo"]
    form_class = FornitoreForm
    form_layout = [("Fornitore", [("nome", "tipo"), ("client_id", "sandbox"), "attivo", "nuova_chiave", "nuovo_segreto"])]
    buttons = ["prova"]
    ai_descrizione = "I fornitori di pagamento online (Stripe, PayPal) con cui l'azienda incassa le fatture dal portale o da un link."

    def layout_dettaglio(self):
        via = {"nuova_chiave", "nuovo_segreto"}
        return [(t, [[c for c in riga if c not in via] for riga in righe if any(c not in via for c in riga)]) for t, righe in super().layout_dettaglio()]

    def col_chiave(self, obj):
        if obj.tipo == obj.FINTO:
            return "—"
        if obj.tipo == obj.PAYPAL:
            return f"{obj.client_id[:8]}…{' (sandbox)' if obj.sandbox else ''}" if obj.client_id and obj.chiave_cifrata else "manca"
        try:
            chiave = obj.chiave()
        except cifratura.SegretoIlleggibile:
            return "illeggibile"
        return (f"{chiave[:8]}… (prova)" if chiave.startswith(("sk_test_", "rk_test_")) else cifratura.mascherato(chiave)) if chiave else "manca"
    col_chiave.short_description = "Chiave"

    def prova(self, request, obj):
        from . import fornitori
        try:
            fornitori.prova(obj)
        except fornitori.ErrorePagamento as e:
            return f"Prova non riuscita: {e}"
        if obj.tipo == obj.FINTO:
            return "Fornitore simulato: nessuna chiave da provare."
        return f"Chiave valida: {obj.get_tipo_display()} risponde."
    prova.short_description = "Prova la chiave"
    prova.ai = False


@register
class PagamentoView(ModelView):
    """I pagamenti online: quelli pagati sono già incassi sulla fattura."""
    model = Pagamento
    slug = "pagamenti"
    company_field = "azienda"
    list_display = ["creato", "fattura", "importo", "stato", "fornitore", "completato_il"]
    list_filter = ["stato"]
    search_fields = ["fattura__numero", "riferimento", "id_esterno"]
    readonly_fields = ["fattura", "fornitore", "importo", "stato", "id_esterno", "url_pagamento", "riferimento", "nota", "creato", "completato_il"]
    form_layout = [("Pagamento", [("fattura", "importo"), ("stato", "fornitore"), ("riferimento", "completato_il"), "nota", "id_esterno"])]
    ai_descrizione = "I pagamenti online delle fatture (Stripe, PayPal): importo, stato, quando sono stati pagati."

    def has_add_permission(self, request):
        return False
