from core.viste import ModelView, register

from .models import Domanda


@register
class DomandeView(ModelView):
    """Che cosa chiede la gente e su quali pagine: si legge, non si scrive."""
    model = Domanda
    slug = "domande"
    list_display = ["creata", "utente", "titolo", "testo"]
    list_filter = ["utente", "creata"]
    search_fields = ["testo", "titolo", "url"]
    form_layout = [("Domanda", [("utente", "creata"), ("titolo", "url"), "testo", "conversazione"])]
    readonly_fields = ["utente", "creata", "titolo", "url", "testo", "conversazione"]
    list_group_by = ["titolo", "utente", "creata:mese"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False if obj is not None else super().has_change_permission(request, obj)
