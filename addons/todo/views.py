from django.utils.html import format_html

from core.viste import ModelView, register

from .models import Attivita, Tag

PILL_STATO = {Attivita.APERTA: "ui-pill-info", Attivita.IN_CORSO: "ui-pill-warn",
              Attivita.FATTA: "ui-pill-ok", Attivita.ANNULLATA: "ui-pill-neutral"}


@register
class AttivitaView(ModelView):
    model = Attivita
    slug = "attivita"
    list_display = ["titolo", "scadenza", "assegnatario", "stato"]
    list_filter = ["stato", "assegnatario", "tag"]
    search_fields = ["titolo", "descrizione"]
    ordering = ["-scadenza", "-creato"]
    form_layout = [
        ("Generale", ["titolo", ("scadenza", "assegnatario"), "descrizione"]),
        ("Classificazione", ["tag", "stato"]),
    ]
    readonly_fields = ["creato"]
    company_field = "azienda"
    actions = ["archivia"]
    buttons = ["segna_fatta"]
    api = True

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creato_da = request.user
        super().save_model(request, obj, form, change)

    def col_stato(self, obj):
        return format_html('<span class="ui-pill {}">{}</span>', PILL_STATO[obj.stato], obj.get_stato_display())
    col_stato.short_description = "Stato"

    def archivia(self, request, queryset):
        n = queryset.update(stato=Attivita.ANNULLATA)
        return f"Attività archiviate: {n}."
    archivia.short_description = "Archivia"

    def segna_fatta(self, request, obj):
        obj.stato = Attivita.FATTA
        obj.save(update_fields=["stato"])
        return f"«{obj}» segnata come fatta."
    segna_fatta.short_description = "Segna fatta"


@register
class TagView(ModelView):
    model = Tag
    list_display = ["nome", "colore"]
    search_fields = ["nome"]
    api = True
