"""Registro IVA delle vendite: documenti emessi nel periodo, con imponibile e imposta per aliquota."""
import csv
from collections import OrderedDict
from decimal import Decimal

from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.dashboard import queryset

from .models import Fattura

MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]


def periodo(request):
    oggi = timezone.localdate()
    anno = request.GET.get("anno", "")
    mese = request.GET.get("mese", "")
    anno = int(anno) if anno.isdigit() else oggi.year
    mese = int(mese) if mese.isdigit() and 1 <= int(mese) <= 12 else (None if "mese" in request.GET else oggi.month)
    return anno, mese


def registro(request, anno, mese=None):
    """(righe, riepilogo): una riga per documento e aliquota; le note di credito con segno negativo."""
    documenti = (queryset(request, Fattura).filter(stato=Fattura.EMESSA, data__year=anno)
                 .select_related("cliente").prefetch_related("righe__aliquota").order_by("data", "pk"))
    if mese:
        documenti = documenti.filter(data__month=mese)
    righe, riepilogo = [], OrderedDict()
    for f in documenti:
        for g in f.riepilogo_iva():
            imponibile, imposta = g["imponibile"] * f.segno, g["imposta"] * f.segno
            righe.append({"fattura": f, "aliquota": g["aliquota"], "imponibile": imponibile, "imposta": imposta})
            voce = riepilogo.setdefault(g["aliquota"].pk, {"aliquota": g["aliquota"], "imponibile": Decimal(0),
                                                           "imposta": Decimal(0)})
            voce["imponibile"] += imponibile
            voce["imposta"] += imposta
    return righe, list(riepilogo.values())


@login_required
@permission_required("fatturazione.view_fattura", raise_exception=True)
def registro_iva(request):
    anno, mese = periodo(request)
    righe, riepilogo = registro(request, anno, mese)
    if request.GET.get("formato") == "csv":
        risposta = HttpResponse(content_type="text/csv; charset=utf-8")
        risposta["Content-Disposition"] = f'attachment; filename="registro-iva-{anno}{f"-{mese:02d}" if mese else ""}.csv"'
        scrittore = csv.writer(risposta, delimiter=";")
        scrittore.writerow(["Data", "Numero", "Tipo", "Cliente", "Partita IVA", "Codice fiscale", "Aliquota",
                            "Imponibile", "Imposta"])
        for r in righe:
            f = r["fattura"]
            scrittore.writerow([f.data.strftime("%d/%m/%Y"), f.numero, f.get_tipo_display(), f.cliente.nome,
                                f.cliente.partita_iva, f.cliente.codice_fiscale, r["aliquota"].codice,
                                f"{r['imponibile']:.2f}".replace(".", ","), f"{r['imposta']:.2f}".replace(".", ",")])
        return risposta
    totale = {"imponibile": sum((v["imponibile"] for v in riepilogo), Decimal(0)),
              "imposta": sum((v["imposta"] for v in riepilogo), Decimal(0))}
    anni = range(timezone.localdate().year, timezone.localdate().year - 6, -1)
    return render(request, "fatturazione/registro_iva.html", {
        "righe": righe, "riepilogo": riepilogo, "totale": totale, "anno": anno, "mese": mese, "anni": anni,
        "mesi": list(enumerate(MESI, start=1)), "titolo_periodo": f"{MESI[mese - 1]} {anno}" if mese else str(anno)})
