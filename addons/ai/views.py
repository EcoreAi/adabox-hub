from core import cifratura
from core.viste import Inline, ModelView, register

from .forms import ChiaveAziendaForm, ProviderForm
from .models import AnelloCatena, ChiaveAzienda, Modello, Profilo, Provider


@register
class ProviderView(ModelView):
    model = Provider
    slug = "provider"
    list_display = ["nome", "tipo", "chiave", "locale", "attivo"]
    form_class = ProviderForm
    form_layout = [("Provider", [("nome", "tipo"), "base_url", ("nuova_chiave", "togli_chiave"), ("locale", "attivo")])]

    def col_chiave(self, obj):
        try:
            return cifratura.mascherato(cifratura.decifra(obj.chiave_cifrata)) or "—"
        except cifratura.SegretoIlleggibile:
            return "illeggibile"
    col_chiave.short_description = "Chiave"


@register
class ChiaveAziendaView(ModelView):
    model = ChiaveAzienda
    slug = "chiavi"
    list_display = ["provider", "azienda", "chiave"]
    form_class = ChiaveAziendaForm
    form_layout = [("Chiave dell'azienda", [("provider", "azienda"), "chiave"])]

    def col_chiave(self, obj):
        try:
            return cifratura.mascherato(cifratura.decifra(obj.chiave_cifrata))
        except cifratura.SegretoIlleggibile:
            return "illeggibile"
    col_chiave.short_description = "Chiave"


@register
class ModelloView(ModelView):
    model = Modello
    slug = "modelli"
    list_display = ["etichetta", "provider", "id_api", "contesto", "prezzo_input", "prezzo_output", "attivo"]
    list_filter = ["provider", "attivo", "residenza_ue"]
    search_fields = ["etichetta", "id_api"]
    form_layout = [("Modello", [("provider", "id_api"), "etichetta", ("contesto", "max_output")]),
                   ("Prezzi in dollari per milione di token", [("prezzo_input", "prezzo_output"),
                                                               ("prezzo_cache_scrittura", "prezzo_cache_lettura")]),
                   ("Capacità", [("strumenti", "visione", "ragionamento"), ("residenza_ue", "attivo")])]


@register
class ProfiloView(ModelView):
    model = Profilo
    slug = "profili"
    list_display = ["nome", "compito", "app", "azienda", "effort", "catena_modelli", "attivo"]
    list_filter = ["compito", "attivo"]
    form_layout = [("Profilo", [("nome", "compito"), ("app", "azienda"), ("effort", "max_token"), "attivo"])]
    inlines = [Inline(AnelloCatena, "profilo", ["modello", "ordine"], titolo="Catena dei modelli (in ordine)")]

    def col_catena_modelli(self, obj):
        return " → ".join(a.modello.etichetta for a in obj.catena.select_related("modello")) or "—"
    col_catena_modelli.short_description = "Catena"
