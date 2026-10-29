from django.utils import timezone
from django.utils.html import format_html

from core.viste import ModelView, register

from .models import Contratto, PoliticaSLA, Supporto


@register
class PoliticaView(ModelView):
    model = PoliticaSLA
    slug = "politiche"
    list_display = ["nome", "risposta_urgente", "risoluzione_urgente", "risposta_media", "risoluzione_media",
                    "ore_lavorative"]
    form_layout = [("Politica", ["nome", ("ore_lavorative", "giorni"), ("inizio_giornata", "fine_giornata")]),
                   ("Prima risposta (ore)", [("risposta_urgente", "risposta_alta", "risposta_media", "risposta_bassa")]),
                   ("Risoluzione (ore)", [("risoluzione_urgente", "risoluzione_alta", "risoluzione_media",
                                           "risoluzione_bassa")])]


@register
class ContrattoView(ModelView):
    model = Contratto
    slug = "contratti"
    list_display = ["nome", "cliente", "politica", "inizio", "fine", "valido"]
    list_filter = ["politica", "attivo"]
    search_fields = ["nome", "cliente__nome"]
    form_layout = [("Contratto", [("nome", "cliente"), ("politica", "attivo"), ("inizio", "fine"), "note"])]
    company_field = "azienda"
    chatter = True

    def col_valido(self, obj):
        oggi = timezone.localdate()
        valido = obj.attivo and obj.inizio <= oggi and (obj.fine is None or obj.fine >= oggi)
        return format_html('<span class="ui-pill {}">{}</span>', "ui-pill-ok" if valido else "ui-pill-neutral",
                           "valido" if valido else "non valido")
    col_valido.short_description = "Oggi"


@register
class SupportoView(ModelView):
    model = Supporto
    slug = "supporto"
    verbose_name_plural = "supporto dei progetti"
    list_display = ["progetto", "team", "responsabile", "contratto", "attivo"]
    list_filter = ["team", "attivo"]
    search_fields = ["progetto__nome", "progetto__codice"]
    form_layout = [("Assistenza del progetto", [("progetto", "attivo"), ("team", "responsabile"), "contratto"]),
                   ("Widget di segnalazione", ["domini"])]
    readonly_fields = ["chiave"]
    company_field = "azienda"
