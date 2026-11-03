from core.viste import ModelView, register

from .models import Capacita


@register
class CapacitaView(ModelView):
    model = Capacita
    slug = "persone"
    list_display = ["utente", "ore_giorno", "quota", "sabato", "domenica"]
    search_fields = ["utente__username", "utente__last_name"]
    form_layout = [("Capacità", ["utente", ("ore_giorno", "quota"), ("sabato", "domenica")])]
    company_field = "azienda"
