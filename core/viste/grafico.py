"""Vista grafico: conteggio o somma per categoria, aggregati nel DB, disegnati in SVG dal server."""
from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils.safestring import mark_safe

from core import svg

from . import filtri, gruppi
from .lista import VistaBase, contesto_testata, urls_di

MAX_CATEGORIE = 30
NOMI_TIPI = {"barre": "Barre", "linee": "Linee", "torta": "Torta"}


def _scelta(valore, ammessi):
    return valore if valore in ammessi else ammessi[0]


def etichetta_misura(vista, misura):
    if misura == "count":
        return "Numero"
    return f"Somma di {vista.etichetta(misura.split(':', 1)[1]).lower()}"


def dati(vista, qs, misura, per):
    """[(etichetta, valore)] aggregati; oltre MAX_CATEGORIE: le prime per valore + 'Altro'
    (per le date: le ultime MAX_CATEGORIE in ordine di tempo)."""
    aggregato = Count("pk") if misura == "count" else Sum(misura.split(":", 1)[1])
    righe = list(qs.annotate(_g=gruppi.espressione(vista, per)).order_by().values("_g")
                 .annotate(_v=aggregato).order_by("_g"))
    nomi = gruppi.etichette(vista, per, [r["_g"] for r in righe])
    intero = misura == "count" or isinstance(vista.opts.get_field(misura.split(":", 1)[1]), models.IntegerField)
    coppie = [(nomi[r["_g"]], int(r["_v"] or 0) if intero else (r["_v"] or 0)) for r in righe]
    if len(coppie) <= MAX_CATEGORIE:
        return coppie
    if ":" in per:
        return coppie[-MAX_CATEGORIE:]
    ordinate = sorted(coppie, key=lambda c: c[1], reverse=True)
    return ordinate[:MAX_CATEGORIE - 1] + [("Altro", sum(v for _, v in ordinate[MAX_CATEGORIE - 1:]))]


class GraficoView(VistaBase):
    def get(self, request):
        vista = self.vista
        if not vista.has_view_permission(request):
            raise PermissionDenied
        g = vista.graph
        tipo = _scelta(request.GET.get("tipo"), list(g.get("tipi", ["barre"])))
        misura = _scelta(request.GET.get("misura"), list(g.get("misure", ["count"])))
        per = _scelta(request.GET.get("per"), list(g["per"]))
        qs = filtri.applica(vista, request, vista.get_queryset(request))
        serie = dati(vista, qs, misura, per)
        titolo = f"{etichetta_misura(vista, misura)} per {dict(gruppi.raggruppabili_grafico(vista)).get(per, per).lower()}"
        return render(request, "core/vista/grafico.html", {
            "vista": vista, "urls": urls_di(vista), "tipo": tipo, "misura": misura, "per": per, "titolo": titolo,
            "tipi": [(t, NOMI_TIPI.get(t, t)) for t in g.get("tipi", ["barre"])],
            "misure": [(m, etichetta_misura(vista, m)) for m in g.get("misure", ["count"])],
            "assi": gruppi.raggruppabili_grafico(vista),
            "svg": mark_safe(svg.DISEGNI[tipo](serie, titolo)) if serie else None,
            "righe": [(e, gruppi.numero(v)) for e, v in serie],
            "totale": gruppi.numero(sum(v for _, v in serie)) if serie else "",
            "filtri": filtri.specifiche(vista, request),
            "extra_get": [("tipo", tipo), ("misura", misura), ("per", per)],
            **contesto_testata(request, vista, "grafico")})
