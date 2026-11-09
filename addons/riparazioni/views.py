from django.core.exceptions import ValidationError
from django.shortcuts import redirect

from core.viste import Inline, ModelView, register, schede

from . import servizi
from .models import GaranziaProdotto, Riparazione, RigaRicambio


def _fai(funzione, request, obj, ok):
    try:
        funzione(obj, request.user)
    except ValidationError as e:
        return " ".join(e.messages)
    return ok


@register
class RiparazioneView(ModelView):
    """Gli ordini di riparazione: ingresso, preventivo, lavorazione con i ricambi, riconsegna e fattura."""
    model = Riparazione
    slug = "riparazioni"
    company_field = "azienda"
    list_display = ["numero", "ricevuta_il", "cliente", "prodotto", "seriale", "stato", "in_garanzia", "tecnico"]
    list_filter = ["stato", "in_garanzia", "tecnico"]
    search_fields = ["numero", "cliente__nome", "seriale", "descrizione_bene"]
    form_layout = [("Ingresso", [("cliente", "ricevuta_il"), ("prodotto", "seriale"), "descrizione_bene", "difetto", "accessori"]),
                   ("Lavoro", [("tecnico", "magazzino"), ("ore", "tariffa"), "in_garanzia", "diagnosi"])]
    readonly_fields = ["numero", "stato", "garanzia_fino_al", "recupero_fornitore", "riconsegnata_il"]
    inlines = [Inline(RigaRicambio, "riparazione", ["prodotto", "quantita", "prezzo"], titolo="Ricambi", extra=0)]
    kanban_group = "stato"
    kanban_ricco = True
    chatter = True
    tracked_fields = ["stato", "in_garanzia"]
    buttons = ["preventivo", "approva", "rifiuta", "avvia", "pronta", "riconsegna", "fattura"]
    ai_descrizione = "Le riparazioni dei beni dei clienti: stato, garanzia, ricambi, ore e costo."

    def save_model(self, request, obj, form, change):
        nuova = not change
        super().save_model(request, obj, form, change)
        if nuova:
            servizi.accetta(obj)

    def kanban_queryset(self, qs):
        return qs.select_related("cliente", "prodotto")

    def kanban_scheda(self, request, obj):
        esito = (*schede.FATTO, "Riconsegnata") if obj.stato == obj.RICONSEGNATA else ("azzurro", "icon-calendar", obj.get_stato_display())
        return schede.scheda(esito, sottotitolo=obj.cliente.nome, righe=[str(obj.prodotto or obj.descrizione_bene), "In garanzia" if obj.in_garanzia else ""])

    def get_buttons(self, request, obj):
        ammessi = {Riparazione.RICEVUTA: {"preventivo"}, Riparazione.PREVENTIVO: {"approva", "rifiuta"}, Riparazione.APPROVATA: {"avvia"},
                   Riparazione.LAVORAZIONE: {"pronta"}, Riparazione.PRONTA: {"riconsegna", "fattura"},
                   Riparazione.RICONSEGNATA: {"fattura"}, Riparazione.RIFIUTATA: {"riconsegna"}}.get(obj.stato, set())
        if obj.in_garanzia or obj.fattura_id:
            ammessi = ammessi - {"fattura"}
        return [b for b in super().get_buttons(request, obj) if b[0] in ammessi]

    def preventivo(self, request, obj):
        return _fai(servizi.preventivo, request, obj, "Fatto.")
    preventivo.short_description = "Preventivo (o ripara se in garanzia)"

    def approva(self, request, obj):
        return _fai(servizi.approva, request, obj, "Preventivo approvato.")
    approva.short_description = "Il cliente approva"

    def rifiuta(self, request, obj):
        return _fai(servizi.rifiuta, request, obj, "Preventivo rifiutato.")
    rifiuta.short_description = "Il cliente rifiuta"

    def avvia(self, request, obj):
        return _fai(servizi.avvia, request, obj, "In lavorazione.")
    avvia.short_description = "Avvia la lavorazione"

    def pronta(self, request, obj):
        return _fai(servizi.pronta, request, obj, "Pronta: i ricambi sono scaricati dal magazzino.")
    pronta.short_description = "Pronta"
    pronta.permission = "magazzino.add_movimento"

    def riconsegna(self, request, obj):
        return _fai(servizi.riconsegna, request, obj, "Riconsegnata.")
    riconsegna.short_description = "Riconsegna al cliente"

    def fattura(self, request, obj):
        try:
            f = servizi.fattura(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return redirect("fatturazione:fatture_dettaglio", pk=f.pk)
    fattura.short_description = "Crea la fattura"
    fattura.permission = "fatturazione.add_fattura"


@register
class GaranziaProdottoView(ModelView):
    model = GaranziaProdotto
    slug = "garanzie"
    company_field = "azienda"
    list_display = ["prodotto", "mesi", "mesi_fornitore"]
    form_layout = [("Garanzia", [("prodotto", "mesi"), "mesi_fornitore", "condizioni"])]
    ai_descrizione = "La durata della garanzia dei prodotti verso i clienti e dei fornitori."
