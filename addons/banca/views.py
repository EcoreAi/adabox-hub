from core.viste import ModelView, register

from .models import Conto, MovimentoBanca


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
