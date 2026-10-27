"""Urlconf dei test delle viste facoltative: una ModelView di prova sui Lavoro, montata sotto /prova/."""
from django.urls import include, path

from config.urls import urlpatterns as base
from core.models import Lavoro
from core.views import SoloSuperuserView


class ProvaView(SoloSuperuserView):
    model = Lavoro
    slug = "lavori"
    list_display = ["funzione", "stato", "tentativi"]
    list_filter = ["stato"]
    search_fields = ["funzione"]
    kanban_group = "stato"
    kanban_fields = ["tentativi"]
    calendar_date = "esegui_dopo"
    graph = {"tipi": ["barre", "linee", "torta"], "misure": ["count", "sum:tentativi"],
             "per": ["stato", "esegui_dopo:mese"]}
    chatter = False

    def _perm(self, request, azione):
        return request.user.is_superuser


VISTA = ProvaView("prova")
urlpatterns = [path("prova/", include((VISTA.get_urls(), "prova"))), *base]
