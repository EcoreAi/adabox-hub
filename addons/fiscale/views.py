from core.viste import ModelView, register

from .models import AliquotaIva, TerminePagamento


@register
class AliquotaView(ModelView):
    model = AliquotaIva
    slug = "aliquote"
    list_display = ["codice", "descrizione", "percentuale", "natura", "esigibilita", "attiva"]
    list_filter = ["attiva", "natura", "esigibilita"]
    search_fields = ["codice", "descrizione"]
    form_layout = [("Aliquota", [("codice", "percentuale"), "descrizione", ("natura", "esigibilita"),
                                 "riferimento_normativo", "attiva"])]
    api = True


@register
class TermineView(ModelView):
    model = TerminePagamento
    slug = "termini"
    list_display = ["nome", "modalita", "attivo"]
    list_filter = ["modalita", "attivo"]
    search_fields = ["nome"]
    form_layout = [("Termine", ["nome", "modalita", "rate", "attivo"])]
    api = True
