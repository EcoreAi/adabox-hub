from core.viste import ModelView, register

from .models import Grafico


@register
class SalvatiView(ModelView):
    """I grafici salvati di chi guarda: si consultano da qui, si creano da Ada, dalle viste Grafico o dal costruttore."""
    model = Grafico
    slug = "salvati"
    list_display = ["titolo", "tipo", "pagina", "origine", "aggiornato"]
    list_filter = ["tipo", "pagina", "origine"]
    search_fields = ["titolo"]
    form_layout = [("Grafico", [("titolo", "tipo"), ("pagina", "aggiorna_ogni"), ("origine", "aggiornato")])]
    readonly_fields = ["origine", "aggiornato"]
    list_group_by = ["tipo", "pagina", "origine"]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(utente=request.user)

    def has_add_permission(self, request):
        return False
