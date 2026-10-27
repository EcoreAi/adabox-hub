from types import SimpleNamespace
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views import View

from . import filtri, gruppi


def urls_di(vista):
    return SimpleNamespace(lista=vista.url("lista"), nuovo=vista.url("nuovo"), esporta=vista.url("esporta"),
                           importa=vista.url("importa"))


def query_filtri(request):
    """Solo ricerca e filtri (q, f_*): passano da una vista all'altra nel selettore."""
    return urlencode([(k, v) for k in request.GET for v in request.GET.getlist(k) if k == "q" or k.startswith("f_")])


def contesto_testata(request, vista, attiva):
    qf = query_filtri(request)
    return {"viste": [(n, e, f"{u}?{qf}" if qf else u, n == attiva) for n, e, u in vista.viste_disponibili()],
            "query_filtri": qf}


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
        raggruppabili = gruppi.raggruppabili(vista)
        chiave = request.GET.get("g", "")
        info_gruppi = None
        if chiave in dict(raggruppabili):
            qs, info_gruppi = gruppi.gruppi(vista, qs, chiave)
        else:
            chiave = ""
        page_obj = Paginator(qs, vista.per_page).get_page(request.GET.get("p"))
        ordine = request.GET.get("o", "")
        ordinabili = filtri.ordinabili(vista)
        colonne = []
        for c in vista.list_display:
            direzione = "asc" if ordine == c else "desc" if ordine == f"-{c}" else ""
            colonne.append({"campo": c, "label": vista.etichetta(c), "ordinabile": c in ordinabili,
                            "direzione": direzione, "prossimo": f"-{c}" if direzione == "asc" else c})
        azioni = [(nome, etichetta, vista.url("azione", nome=nome)) for nome, etichetta in vista.get_actions(request)]
        stampe = [(r["nome"], vista.url("stampa_massa", indice=i)) for i, r in enumerate(vista.reports)]
        righe = [(obj, [vista.col_valore(request, obj, c) for c in vista.list_display]) for obj in page_obj]
        somme = gruppi.somme_ammesse(vista)
        tot = gruppi.totali(vista, qs)
        ctx = {
            "vista": vista, "urls": urls_di(vista), "colonne": colonne, "righe": righe,
            "blocchi": _blocchi(vista, righe, info_gruppi),
            "totali": [tot.get(c, "") for c in vista.list_display] if tot else None,
            "raggruppabili": raggruppabili, "gruppo": chiave, "con_somme": bool(somme), "stampe": stampe,
            "selezione": bool(azioni or stampe),
            **contesto_testata(request, vista, "lista"),
            "filtri": filtri.specifiche(vista, request), "page_obj": page_obj,
            "q": request.GET.get("q", ""), "puo_aggiungere": vista.has_add_permission(request),
            "azioni": azioni,
        }
        return render(request, vista.template_tabella if parziale(request) else vista.template_lista, ctx)


def _blocchi(vista, righe, info):
    """Le righe della pagina divise per gruppo: [{etichetta, n, somme (per colonna), righe}]; un solo blocco
    senza intestazione se non si raggruppa."""
    if info is None:
        return [{"etichetta": None, "righe": righe}]
    blocchi = []
    for obj, celle in righe:
        if not blocchi or blocchi[-1]["valore"] != obj._gruppo:
            g = info.get(obj._gruppo, {"etichetta": "—", "n": 0, "somme": {}})
            blocchi.append({"valore": obj._gruppo, "etichetta": g["etichetta"], "n": g["n"],
                            "somme": [g["somme"].get(c, "") for c in vista.list_display], "righe": []})
        blocchi[-1]["righe"].append((obj, celle))
    return blocchi
