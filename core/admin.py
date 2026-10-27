from django.contrib import admin

from .models import Azienda, ProfiloUtente


@admin.register(Azienda)
class AziendaAdmin(admin.ModelAdmin):
    list_display = ("nome", "partita_iva", "citta", "attiva")
    list_filter = ("attiva",)
    search_fields = ("nome", "partita_iva")


@admin.register(ProfiloUtente)
class ProfiloUtenteAdmin(admin.ModelAdmin):
    list_display = ("utente", "azienda_predefinita")
    filter_horizontal = ("aziende",)
