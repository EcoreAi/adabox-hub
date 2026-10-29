from django.contrib import admin, messages

from .models import Azienda, Modulo, Parametro, Pianificazione, ProfiloUtente, Sequenza, TokenApi


@admin.register(Azienda)
class AziendaAdmin(admin.ModelAdmin):
    list_display = ("nome", "partita_iva", "citta", "attiva")
    list_filter = ("attiva",)
    search_fields = ("nome", "partita_iva")


@admin.register(ProfiloUtente)
class ProfiloUtenteAdmin(admin.ModelAdmin):
    list_display = ("utente", "azienda_predefinita")
    filter_horizontal = ("aziende",)


@admin.register(Modulo)
class ModuloAdmin(admin.ModelAdmin):
    """Specchio in sola lettura del file di stato: installare, aggiornare e disinstallare passano dalla pagina /moduli/;
    qui (solo superuser) le azioni per accendere e spegnere i moduli installati."""
    list_display = ("slug", "nome", "versione_installata", "versione_disponibile", "stato", "attivo", "application")
    list_filter = ("stato", "disattivato", "application")
    actions = ["disattiva", "riattiva"]

    @admin.display(boolean=True, description="attivo", ordering="disattivato")
    def attivo(self, obj):
        return not obj.disattivato

    def _attivazione(self, request, queryset, attivo):
        from .registry import modules
        if not request.user.is_superuser:
            self.message_user(request, "Solo un superuser accende e spegne i moduli.", messages.ERROR)
            return
        fatti = [m.nome for m in queryset if modules.imposta_attivo(m.slug, attivo)]
        saltati = queryset.count() - len(fatti)
        if fatti:
            self.message_user(request, f"{'Riattivati' if attivo else 'Disattivati'}: {', '.join(fatti)}.")
        if saltati:
            self.message_user(request, f"{saltati} non installati: saltati.", messages.WARNING)

    @admin.action(description="Disattiva i moduli selezionati (nascosti a tutti, i dati restano)")
    def disattiva(self, request, queryset):
        self._attivazione(request, queryset, False)

    @admin.action(description="Riattiva i moduli selezionati")
    def riattiva(self, request, queryset):
        self._attivazione(request, queryset, True)
    search_fields = ("slug", "nome")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TokenApi)
class TokenApiAdmin(admin.ModelAdmin):
    """La chiave è un hash: dall'admin si vede e si revoca, non si crea (si crea dal profilo)."""
    list_display = ("nome", "utente", "creato", "ultimo_uso", "attivo")
    list_filter = ("attivo",)
    search_fields = ("nome", "utente__username")
    readonly_fields = ("utente", "nome", "creato", "ultimo_uso")

    def has_add_permission(self, request):
        return False


@admin.register(Pianificazione)
class PianificazioneAdmin(admin.ModelAdmin):
    """Le pianificazioni nascono dai manifest: dall'admin si attivano, si disattivano e si anticipano."""
    list_display = ("nome", "modulo", "funzione", "ogni", "alle", "attiva", "prossima_esecuzione", "ultima_esecuzione")
    list_editable = ("attiva",)
    list_filter = ("modulo", "attiva")
    readonly_fields = ("modulo", "nome", "funzione", "ogni", "alle", "ultima_esecuzione")

    def has_add_permission(self, request):
        return False


@admin.register(Sequenza)
class SequenzaAdmin(admin.ModelAdmin):
    list_display = ("codice", "azienda", "formato", "prossimo", "azzera", "anno")
    list_filter = ("azienda", "azzera")
    search_fields = ("codice",)


@admin.register(Parametro)
class ParametroAdmin(admin.ModelAdmin):
    list_display = ("chiave", "azienda", "valore")
    list_filter = ("azienda",)
    search_fields = ("chiave",)
