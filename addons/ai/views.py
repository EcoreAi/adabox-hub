from core import cifratura
from core.viste import Inline, ModelView, register

from .forms import ChiaveAziendaForm, PianificataForm, ProviderForm
from .models import AnelloCatena, ChiaveAzienda, Modello, Pianificata, Profilo, Provider, Turno


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


@register
class PianificataView(ModelView):
    """Le attività che l'assistente esegue da solo: ognuno vede le proprie, gli amministratori tutte."""
    model = Pianificata
    slug = "pianificate"
    list_display = ["nome", "quando", "attiva", "prossima", "esito"]
    list_filter = ["attiva", "ricorrenza"]
    search_fields = ["nome", "istruzioni"]
    form_class = PianificataForm
    form_layout = [("Attività", ["nome", "istruzioni", "ambito"]),
                   ("Quando", [("ricorrenza", "alle"), "giorni", ("giorno_mese", "ogni_ore", "minuti_prima")]),
                   ("Risultato (sempre anche nella sua chat)", [("in_discuss", "per_email"), "attiva"])]
    readonly_fields = ["utente", "prossima", "ultima", "esito", "errori", "conversazione"]
    buttons = ["esegui_ora", "sospendi", "riattiva"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(utente=request.user)

    def save_model(self, request, obj, form, change):
        from .pianificate import calcola_prossima
        if not change:
            obj.utente, obj.azienda = request.user, getattr(request, "azienda", None)
        obj.prossima = calcola_prossima(obj) if obj.attiva else None
        if obj.attiva:
            obj.errori = 0
        super().save_model(request, obj, form, change)

    def col_quando(self, obj):
        return obj.frequenza()
    col_quando.short_description = "Quando"

    def col_conversazione(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        if not obj.conversazione_id:
            return "—"
        return format_html('<a href="{}">Apri la chat dei risultati</a>', reverse("ai:conversazione",
                                                                                   args=[obj.conversazione_id]))
    col_conversazione.short_description = "Risultati"

    def get_buttons(self, request, obj):
        nascosto = "sospendi" if not obj.attiva else "riattiva"
        return [(n, e) for n, e in super().get_buttons(request, obj) if n != nascosto]

    def esegui_ora(self, request, obj):
        from core import lavori
        lavori.accoda("ai.pianificate.esegui_id", pianificata_id=obj.pk, utente=request.user)
        return "Esecuzione avviata: il risultato arriva nella chat dei risultati tra poco."
    esegui_ora.short_description = "Esegui ora"

    def sospendi(self, request, obj):
        obj.attiva, obj.prossima = False, None
        obj.save(update_fields=["attiva", "prossima"])
        return f"«{obj}» sospesa."
    sospendi.short_description = "Sospendi"

    def riattiva(self, request, obj):
        from .pianificate import calcola_prossima
        obj.attiva, obj.errori, obj.prossima = True, 0, calcola_prossima(obj)
        obj.save(update_fields=["attiva", "errori", "prossima"])
        return f"«{obj}» riattivata: prossima esecuzione {obj.frequenza()}."
    riattiva.short_description = "Riattiva"
