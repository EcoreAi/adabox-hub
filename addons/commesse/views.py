from core.viste import Inline, ModelView, register

from .models import Condizioni, CostoOrario, TariffaPersona, Tappa


@register
class CondizioniView(ModelView):
    model = Condizioni
    slug = "condizioni"
    list_display = ["progetto", "tipo", "tariffa", "importo_corpo"]
    list_filter = ["tipo"]
    search_fields = ["progetto__nome", "progetto__cliente__nome"]
    form_layout = [("Fatturazione", ["progetto", "tipo", ("tariffa", "importo_corpo"), ("termine_pagamento", "aliquota")])]
    company_field = "azienda"
    inlines = [Inline(TariffaPersona, "condizioni", ["utente", "tariffa"], titolo="Tariffe delle persone", extra=1),
               Inline(Tappa, "condizioni", ["nome", "percentuale", "importo", "prevista_il"], titolo="Tappe (per i progetti a tappe)", extra=0)]


@register
class CostoOrarioView(ModelView):
    model = CostoOrario
    slug = "costi"
    list_display = ["utente", "costo", "dal"]
    list_filter = ["utente"]
    search_fields = ["utente__username", "utente__last_name"]
    form_layout = [("Costo", ["utente", ("costo", "dal")])]
    company_field = "azienda"
