from core import cifratura
from core.viste import Inline, ModelView, register

from .forms import ChiaveAziendaForm, ProviderForm
from .models import AnelloCatena, ChiaveAzienda, Modello, Profilo, Provider, Turno


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


@register
class ConsumiView(ModelView):
    """Ogni chiamata ai modelli (turni della chat, titoli, pianificate): token, costo, esito."""
    model = Turno
    slug = "consumi"
    verbose_name_plural = "consumi"
    list_display = ["iniziato", "utente", "azienda", "compito", "modello", "passi", "costo", "stato"]
    list_filter = ["compito", "stato", "modello", "azienda", "iniziato"]
    search_fields = ["utente__username", "testo", "errore"]
    form_layout = [("Turno", [("iniziato", "finito"), ("utente", "azienda"), ("compito", "modello"),
                              ("stato", "passi"), ("costo", "uso"), "errore"])]
    readonly_fields = ["iniziato", "finito", "utente", "azienda", "compito", "modello", "stato", "passi", "costo",
                       "uso", "errore"]
    list_group_by = ["iniziato:mese", "utente", "modello", "compito", "azienda"]
    list_sum = ["costo"]
    graph = {"tipi": ["barre", "linee", "torta"], "misure": ["sum:costo", "count"],
             "per": ["iniziato:mese", "utente", "modello", "compito"]}

    def col_costo(self, obj):
        return f"{obj.costo:.4f} $"
    col_costo.short_description = "Costo"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
