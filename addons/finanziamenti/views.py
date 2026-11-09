from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.utils import timezone

from core.viste import ModelView, register

from . import piano
from .models import Finanziamento, RataFinanziamento


def _fai(funzione, *args, ok=""):
    try:
        esito = funzione(*args)
    except ValidationError as e:
        return " ".join(e.messages)
    return ok.format(esito=esito) if ok else None


@register
class FinanziamentoView(ModelView):
    """Mutui e finanziamenti con il piano delle rate."""
    model = Finanziamento
    slug = "finanziamenti"
    company_field = "azienda"
    list_display = ["nome", "tipo", "ente", "capitale", "tasso", "durata", "erogato_il", "stato"]
    list_filter = ["stato", "tipo", "ente"]
    search_fields = ["nome", "numero_contratto", "ente__nome"]
    form_layout = [("Finanziamento", [("nome", "tipo"), ("ente", "numero_contratto"), ("capitale", "tasso"),
                                      ("erogato_il", "responsabile")]),
                   ("Piano", [("durata", "periodicita"), ("ammortamento", "preammortamento"), ("prima_rata", "spese_rata"),
                              "iban_addebito"]),
                   ("Note", ["note"])]
    readonly_fields = ["stato"]
    list_sum = ["capitale"]
    chatter = True
    tracked_fields = ["capitale", "tasso", "durata", "prima_rata"]
    ai_descrizione = "I finanziamenti e mutui dell'azienda con il piano delle rate e il debito residuo."
    buttons = ["rigenera", "estingui"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        campi_piano = {"capitale", "tasso", "durata", "periodicita", "ammortamento", "prima_rata", "preammortamento", "spese_rata"}
        if obj.stato == Finanziamento.ATTIVO and (not change or campi_piano & set(form.changed_data)):
            piano.genera(obj)                       # le rate già pagate restano, le altre si ricalcolano

    def get_buttons(self, request, obj):
        if obj is None or obj.stato == Finanziamento.ESTINTO:
            return []
        return super().get_buttons(request, obj)

    def rigenera(self, request, obj):
        return _fai(piano.genera, obj, ok="Piano ricalcolato: {esito} rate da pagare.")
    rigenera.short_description = "Ricalcola il piano"

    def estingui(self, request, obj):
        return redirect("finanziamenti:estingui", pk=obj.pk)
    estingui.short_description = "Estinzione anticipata"
    estingui.ai = False


@register
class RataView(ModelView):
    """Le rate da pagare di tutti i finanziamenti."""
    model = RataFinanziamento
    slug = "rate"
    company_field = "azienda"
    list_display = ["data", "finanziamento", "numero", "quota_capitale", "quota_interessi", "importo", "debito_residuo", "pagata"]
    list_filter = ["pagata", "finanziamento", "data"]
    search_fields = ["finanziamento__nome"]
    form_layout = [("Rata", [("finanziamento", "numero"), "data", ("quota_capitale", "quota_interessi", "spese"), "importo",
                             ("pagata", "pagata_il")])]
    readonly_fields = ["finanziamento", "numero", "quota_capitale", "quota_interessi", "spese", "importo", "debito_residuo",
                       "pagata", "pagata_il"]
    list_sum = ["importo", "quota_capitale", "quota_interessi"]
    list_group_by = ["finanziamento", "data:mese", "data:anno"]
    calendar_date = "data"
    graph = {"tipi": ["barre", "linee"], "misure": ["sum:importo", "sum:quota_interessi"], "per": ["data:mese", "data:anno", "finanziamento"]}
    ai_descrizione = "Le rate dei finanziamenti con scadenza, quote e se sono pagate."
    buttons = ["paga", "annulla_pagamento"]

    def has_add_permission(self, request):
        return False

    def get_buttons(self, request, obj):
        if obj is None:
            return []
        scelto = "annulla_pagamento" if obj.pagata else "paga"
        return [b for b in super().get_buttons(request, obj) if b[0] == scelto]

    def paga(self, request, obj):
        return redirect("finanziamenti:paga", pk=obj.pk)
    paga.short_description = "Paga"
    paga.ai = False

    def annulla_pagamento(self, request, obj):
        piano.annulla_pagamento(obj, request.user)
        return "Pagamento annullato."
    annulla_pagamento.short_description = "Annulla il pagamento"
    annulla_pagamento.rischio = "irreversibile"
