"""Urlconf di prova per le righe dei documenti: un'azienda con righe di tipo Lavoro (fk azienda)."""
from django.urls import include, path

from config.urls import urlpatterns as base
from core.models import Azienda, Lavoro
from core.viste import Inline, ModelView


class DocumentoProva(ModelView):
    model = Azienda
    slug = "documenti"
    list_display = ["nome"]
    form_layout = [("Documento", ["nome"])]
    inlines = [Inline(Lavoro, "azienda", ["funzione", "max_tentativi"], titolo="Righe")]
    chiamate = []

    def dopo_righe(self, request, obj):
        self.chiamate.append(obj.pk)

    def totali(self, obj):
        return [("Righe", obj.lavoro_set.count())]


VISTA = DocumentoProva("prova")
urlpatterns = [path("prova/", include((VISTA.get_urls(), "prova"))), *base]
