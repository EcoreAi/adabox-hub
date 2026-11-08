"""Il registro delle visite: pagine, permessi, API e accesso di Ada."""
from django.utils import timezone

from core.viste import ModelView, register

from . import servizi
from .models import Visita


@register
class VisitaView(ModelView):
    model = Visita
    slug = "visite"
    list_display = ["nome", "societa", "ospite", "entrata", "uscita", "motivo"]
    list_filter = ["ospite", "entrata", "prevista_il"]
    search_fields = ["nome", "societa", "email", "motivo", "badge"]
    form_layout = [("Visitatore", [("nome", "societa"), ("email", "telefono")]),
                   ("Visita", [("ospite", "motivo"), "prevista_il", ("entrata", "uscita"), ("badge", "privacy")])]
    readonly_fields = ["creato"]
    company_field = "azienda"
    list_group_by = ["ospite", "entrata:giorno", "societa"]
    chatter = True
    buttons = ["segna_entrata", "segna_uscita"]
    actions = ["uscita_selezionate"]
    api = True
    ai_descrizione = "Il registro dei visitatori: chi è entrato, da quale azienda, chi lo riceve, quando è entrato e uscito, chi è presente ora."

    def get_buttons(self, request, obj):
        nomi = {"segna_entrata"} if obj.entrata is None else ({"segna_uscita"} if obj.uscita is None else set())
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in nomi]

    def segna_entrata(self, request, obj):
        servizi.entra(obj.azienda, obj.nome, obj.societa, obj.ospite, obj.motivo, obj.email, obj.telefono, request.user)
        return f"{obj} è entrato."
    segna_entrata.short_description = "Segna entrata"

    def segna_uscita(self, request, obj):
        servizi.esce(obj, request.user)
        return f"{obj} è uscito."
    segna_uscita.short_description = "Segna uscita"

    def uscita_selezionate(self, request, queryset):
        presenti = list(queryset.filter(entrata__isnull=False, uscita__isnull=True))
        for v in presenti:
            servizi.esce(v, request.user)
        return f"Uscite registrate: {len(presenti)}."
    uscita_selezionate.short_description = "Segna uscita"

    def col_entrata(self, obj):
        return timezone.localtime(obj.entrata).strftime("%d/%m %H:%M") if obj.entrata else (
            f"attesa {timezone.localtime(obj.prevista_il):%d/%m %H:%M}" if obj.prevista_il else "—")
    col_entrata.short_description = "Entrata"
