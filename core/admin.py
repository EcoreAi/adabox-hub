from django.contrib import admin

from .models import Azienda, Modulo, ProfiloUtente, TokenApi


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
    """Specchio in sola lettura del file di stato: le operazioni passano dalla pagina /moduli/."""
    list_display = ("slug", "nome", "versione_installata", "versione_disponibile", "stato", "application")
    list_filter = ("stato", "application")
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
