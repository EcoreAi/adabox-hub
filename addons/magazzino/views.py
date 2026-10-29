from django.core.exceptions import ValidationError

from core.viste import Inline, ModelView, register

from . import operazioni
from .models import Consegna, Magazzino, Movimento, Ricevimento, RigaConsegna, RigaRicevimento


@register
class MagazzinoView(ModelView):
    model = Magazzino
    slug = "magazzini"
    list_display = ["nome", "indirizzo", "predefinito"]
    form_layout = [("Magazzino", ["nome", "indirizzo", "predefinito"])]
    company_field = "azienda"


@register
class MovimentoView(ModelView):
    """Movimenti: nascono da consegne e ricevimenti; a mano solo le rettifiche (inventario, scarti)."""
    model = Movimento
    slug = "movimenti"
    list_display = ["data", "prodotto", "magazzino", "tipo", "quantita", "causale"]
    list_filter = ["tipo", "magazzino", "prodotto", "data"]
    search_fields = ["prodotto__nome", "prodotto__codice", "causale"]
    form_layout = [("Rettifica", [("prodotto", "magazzino"), "quantita", "causale"])]
    company_field = "azienda"
    list_group_by = ["prodotto", "tipo", "magazzino", "data:mese"]
    list_sum = ["quantita"]
    api = True

    def has_change_permission(self, request, obj=None):
        return False                                   # i movimenti non si correggono: si rettifica

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.tipo, obj.utente = Movimento.RETTIFICA, request.user
        super().save_model(request, obj, form, change)


def _bottone(request, funzione, obj, messaggio):
    try:
        funzione(obj, request.user)
    except ValidationError as e:
        return " ".join(e.messages)
    return messaggio(obj)


@register
class ConsegnaView(ModelView):
    model = Consegna
    slug = "consegne"
    list_display = ["documento", "cliente", "data", "riferimento", "stato"]
    list_filter = ["stato", "cliente", "magazzino", "data"]
    search_fields = ["numero", "riferimento", "cliente__nome"]
    form_layout = [("Consegna", [("cliente", "magazzino"), ("data", "riferimento"), ("causale_trasporto", "trasporto_a_cura"),
                                 ("vettore", "colli"), ("peso", "aspetto_beni"), "note"])]
    readonly_fields = ["numero", "stato"]
    company_field = "azienda"
    inlines = [Inline(RigaConsegna, "consegna", ["prodotto", "descrizione", "quantita"], titolo="Merce")]
    kanban_group = "stato"
    kanban_fields = ["cliente", "data", "riferimento"]
    chatter = True
    tracked_fields = ["stato"]
    buttons = ["spedisci", "annulla"]
    reports = [{"nome": "DDT", "template": "magazzino/report/ddt.html"}]
    api = True

    def col_documento(self, obj):
        return str(obj)
    col_documento.short_description = "Documento"

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.stato == Consegna.BOZZA)

    def get_buttons(self, request, obj):
        return super().get_buttons(request, obj) if obj.stato == Consegna.BOZZA else []

    def spedisci(self, request, obj):
        return _bottone(request, operazioni.spedisci, obj, lambda c: f"Consegna spedita con il DDT {c.numero}.")
    spedisci.short_description = "Spedisci (emetti DDT)"
    spedisci.rischio = "irreversibile"

    def annulla(self, request, obj):
        if obj.stato != Consegna.BOZZA:
            return "Solo una consegna da spedire si annulla."
        obj.stato = Consegna.ANNULLATO
        obj.save(update_fields=["stato"])
        return "Consegna annullata."
    annulla.short_description = "Annulla"


@register
class RicevimentoView(ModelView):
    model = Ricevimento
    slug = "ricevimenti"
    list_display = ["fornitore", "data", "riferimento", "ddt_fornitore", "stato"]
    list_filter = ["stato", "fornitore", "magazzino", "data"]
    search_fields = ["riferimento", "ddt_fornitore", "fornitore__nome"]
    form_layout = [("Ricevimento", [("fornitore", "magazzino"), ("data", "ddt_fornitore"), "riferimento", "note"])]
    readonly_fields = ["stato"]
    company_field = "azienda"
    inlines = [Inline(RigaRicevimento, "ricevimento", ["prodotto", "quantita"], titolo="Merce")]
    kanban_group = "stato"
    kanban_fields = ["fornitore", "data"]
    chatter = True
    tracked_fields = ["stato"]
    buttons = ["ricevi"]
    api = True

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.stato == Ricevimento.BOZZA)

    def get_buttons(self, request, obj):
        return super().get_buttons(request, obj) if obj.stato == Ricevimento.BOZZA else []

    def ricevi(self, request, obj):
        return _bottone(request, operazioni.ricevi, obj, lambda r: "Merce ricevuta e caricata a magazzino.")
    ricevi.short_description = "Ricevi la merce"
    ricevi.rischio = "irreversibile"
