from types import SimpleNamespace

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views import View

from . import filtri


def urls_di(vista):
    return SimpleNamespace(lista=vista.url("lista"), nuovo=vista.url("nuovo"))


def parziale(request):
    return bool(request.GET.get("partial") or request.headers.get("HX-Request"))


class VistaBase(LoginRequiredMixin, View):
    vista = None


class ListaView(VistaBase):
    def get(self, request):
        vista = self.vista
        if not vista.has_view_permission(request):
            raise PermissionDenied
        qs = filtri.applica(vista, request, vista.get_queryset(request))
        page_obj = Paginator(qs, vista.per_page).get_page(request.GET.get("p"))
        ordine = request.GET.get("o", "")
        ordinabili = filtri.ordinabili(vista)
        colonne = []
        for c in vista.list_display:
            direzione = "asc" if ordine == c else "desc" if ordine == f"-{c}" else ""
            colonne.append({"campo": c, "label": vista.etichetta(c), "ordinabile": c in ordinabili,
                            "direzione": direzione, "prossimo": f"-{c}" if direzione == "asc" else c})
        azioni = [(nome, etichetta, vista.url("azione", nome=nome)) for nome, etichetta in vista.get_actions(request)]
        ctx = {
            "vista": vista, "urls": urls_di(vista), "colonne": colonne,
            "righe": [(obj, [vista.col_valore(request, obj, c) for c in vista.list_display]) for obj in page_obj],
            "filtri": filtri.specifiche(vista, request), "page_obj": page_obj,
            "q": request.GET.get("q", ""), "puo_aggiungere": vista.has_add_permission(request),
            "azioni": azioni,
        }
        return render(request, vista.template_tabella if parziale(request) else vista.template_lista, ctx)
