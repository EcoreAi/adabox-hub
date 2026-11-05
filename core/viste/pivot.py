"""La vista Pivot di una lista: righe, colonne e una o più misure, calcolate dal database con i permessi, l'azienda e i
filtri della lista. Le misure e gli assi ammessi sono quelli che opzioni_vista dà anche al costruttore dei grafici."""
from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import render

from core.esporta import xlsx_bytes

from . import filtri
from .interroga import TRONCATURE, ErroreInterrogazione, _etichette_gruppi, _misura, _numero, _percorso, opzioni_vista
from .lista import VistaBase, contesto_testata, urls_di

RIGHE_MASSIME = 100
COLONNE_MASSIME = 30
MISURE_MASSIME = 3


def _espressione(vista, asse):
    nome, _, parte = asse.partition(":")
    lookup, f, _ = _percorso(vista, nome, con_operatore=False)
    if parte:
        if parte not in TRONCATURE or not isinstance(f, (models.DateField, models.DateTimeField)):
            raise ErroreInterrogazione(f"Asse «{asse}» non valido.")
        return TRONCATURE[parte](lookup), f, parte
    return F(lookup), f, ""


def calcola(vista, request, riga, colonna, misure):
    """{"righe": [{"etichetta", "celle": [[valori per misura]], "totali"}], "colonne": [...], "totali_colonne", "totale"}."""
    qs = filtri.applica(vista, request, vista.get_queryset(request)).order_by()
    if qs.query.distinct:                               # filtro su una relazione multipla: senza doppioni nelle somme
        qs = vista.model._default_manager.filter(pk__in=qs.values("pk"))
    espressioni = {f"m{i}": _misura(vista, m) for i, m in enumerate(misure)}
    calcoli = {k: v[0] for k, v in espressioni.items()}
    formati = [v[1] for v in espressioni.values()]

    def numeri(r):
        return [_numero(r[f"m{i}"], formati[i]) for i in range(len(misure))]

    esp_r, f_r, parte_r = _espressione(vista, riga)
    base = qs.annotate(_r=esp_r)
    per_riga = list(base.values("_r").annotate(**calcoli).order_by("_r")[:RIGHE_MASSIME + 1])
    tagliate = len(per_riga) > RIGHE_MASSIME
    per_riga = per_riga[:RIGHE_MASSIME]
    etichette_r = _etichette_gruppi(f_r, parte_r, [r["_r"] for r in per_riga])
    totale = numeri(qs.aggregate(**calcoli))
    if not colonna:
        return {"colonne": [], "totali_colonne": [], "totale": totale, "tagliate": tagliate,
                "righe": [{"etichetta": etichette_r[r["_r"]], "celle": [], "totali": numeri(r)} for r in per_riga]}
    esp_c, f_c, parte_c = _espressione(vista, colonna)
    per_colonna = list(qs.annotate(_c=esp_c).values("_c").annotate(**calcoli).order_by("_c")[:COLONNE_MASSIME + 1])
    tagliate = tagliate or len(per_colonna) > COLONNE_MASSIME
    per_colonna = per_colonna[:COLONNE_MASSIME]
    chiavi_c = [c["_c"] for c in per_colonna]
    etichette_c = _etichette_gruppi(f_c, parte_c, chiavi_c)
    celle = {(r["_r"], r["_c"]): numeri(r) for r in base.annotate(_c=esp_c).values("_r", "_c").annotate(**calcoli).order_by()
             if r["_r"] in etichette_r and r["_c"] in etichette_c}
    vuota = [""] * len(misure)
    return {"colonne": [etichette_c[c] for c in chiavi_c], "totali_colonne": [numeri(c) for c in per_colonna], "totale": totale, "tagliate": tagliate,
            "righe": [{"etichetta": etichette_r[r["_r"]], "celle": [celle.get((r["_r"], c), vuota) for c in chiavi_c], "totali": numeri(r)} for r in per_riga]}


def tabella_piatta(dati, nomi_misure):
    """(intestazioni, righe) per l'esportazione: una colonna per ogni colonna e misura."""
    con_nomi = len(nomi_misure) > 1
    intestazioni = [""]
    for c in dati["colonne"]:
        intestazioni += [f"{c} · {m}" if con_nomi else c for m in nomi_misure]
    intestazioni += [f"Totale · {m}" if con_nomi else "Totale" for m in nomi_misure]
    righe = []
    for r in dati["righe"]:
        righe.append([r["etichetta"], *[v for cella in r["celle"] for v in cella], *r["totali"]])
    righe.append(["Totale", *[v for cella in dati["totali_colonne"] for v in cella], *dati["totale"]])
    return intestazioni, righe


class PivotView(VistaBase):
    def get(self, request):
        vista = self.vista
        if not vista.has_view_permission(request):
            raise PermissionDenied
        opzioni = opzioni_vista(vista)
        assi, misure_ammesse = dict(opzioni["raggruppamenti"]), dict(opzioni["misure"])
        riga = request.GET.get("riga") if request.GET.get("riga") in assi else (vista.list_group_by[0] if vista.list_group_by[0] in assi else next(iter(assi), ""))
        colonna = request.GET.get("colonna") if request.GET.get("colonna") in assi else ""
        misure = [m for m in request.GET.getlist("misura") if m in misure_ammesse][:MISURE_MASSIME] or (
            [f"sum:{vista.list_sum[0]}"] if vista.list_sum and f"sum:{vista.list_sum[0]}" in misure_ammesse else ["count"])
        errore, dati = "", None
        try:
            dati = calcola(vista, request, riga, colonna, misure) if riga else None
        except ErroreInterrogazione as e:
            errore = str(e)
        nomi = [misure_ammesse[m] for m in misure]
        if dati and request.GET.get("formato") == "xlsx":
            intestazioni, righe = tabella_piatta(dati, nomi)
            risposta = HttpResponse(xlsx_bytes(intestazioni, righe, "Pivot"), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            risposta["Content-Disposition"] = f'attachment; filename="pivot-{vista.slug}.xlsx"'
            return risposta
        return render(request, "core/vista/pivot.html", {
            "vista": vista, "urls": urls_di(vista), **contesto_testata(request, vista, "pivot"), "assi": opzioni["raggruppamenti"], "opzioni_misure": opzioni["misure"],
            "riga": riga, "colonna": colonna, "misure": misure, "nomi_misure": nomi, "dati": dati, "errore": errore,
            "filtri_attivi": [(k, v) for k in request.GET for v in request.GET.getlist(k) if k == "q" or k.startswith("f_")],
            "query": request.GET.urlencode(), "righe_massime": RIGHE_MASSIME, "colonne_massime": COLONNE_MASSIME})
