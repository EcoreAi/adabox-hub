from django.contrib import admin

from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "email", "attivo", "creato")
    list_filter = ("attivo", "creato")
    search_fields = ("nome", "email")
    date_hierarchy = "creato"
    list_per_page = 25
    fieldsets = (
        (None, {"fields": ("nome", "email", "attivo")}),
        ("Altro", {"fields": ("note",), "classes": ("collapse",)}),
    )
