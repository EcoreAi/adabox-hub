from core.viste import ModelView, register

from .models import Canale


@register
class CanaleView(ModelView):
    """Gestione dei canali per i responsabili (archiviare, rinominare); la conversazione è in /discuss/."""
    model = Canale
    slug = "canali"
    list_display = ["__str__", "tipo", "creato_da", "creato", "archiviato"]
    list_filter = ["tipo", "archiviato"]
    search_fields = ["nome", "descrizione"]
    form_layout = [("Canale", [("nome", "tipo"), "descrizione", "archiviato"])]
    readonly_fields = ["creato_da", "creato"]

    def get_queryset(self, request):
        return super().get_queryset(request).exclude(tipo=Canale.DIRETTO)    # i messaggi diretti restano privati
