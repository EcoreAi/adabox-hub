"""Scadenziario a fasce: quanto è aperto per ogni controparte e da quanto è scaduto. Serve clienti e fornitori:
a chi lo usa basta passare le voci, una per scadenza aperta."""
import csv
import io
from decimal import Decimal

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone

from core import report
from core.dashboard import queryset

from .models import Fattura, Scadenza

FASCE = [("a_scadere", "A scadere"), ("f30", "1-30 giorni"), ("f60", "31-60 giorni"), ("f90", "61-90 giorni"),
         ("oltre", "Oltre 90 giorni")]
CHIAVI = [c for c, _ in FASCE]


def fascia(data, oggi):
    """Una scadenza senza data non è scaduta: l'importo resta da pagare, ma non si può dire da quanto."""
    giorni = (oggi - data).days if data else 0
    if giorni <= 0:
        return "a_scadere"
    return "f30" if giorni <= 30 else "f60" if giorni <= 60 else "f90" if giorni <= 90 else "oltre"


def tabella(voci, oggi):
    """voci: (pk della controparte, nome, data, residuo). Restituisce (righe per esposizione decrescente, totali)."""
    per_controparte = {}
    totali = dict.fromkeys(CHIAVI + ["totale", "scaduto"], Decimal(0))
    for pk, nome, data, residuo in voci:
        if residuo <= 0:
            continue
        riga = per_controparte.setdefault(pk, {"pk": pk, "nome": nome, **dict.fromkeys(CHIAVI + ["totale", "scaduto"], Decimal(0))})
        chiave = fascia(data, oggi)
        for destinazione in (riga, totali):
            destinazione[chiave] += residuo
            destinazione["totale"] += residuo
            if chiave != "a_scadere":
                destinazione["scaduto"] += residuo
    righe = sorted(per_controparte.values(), key=lambda r: (-r["totale"], r["nome"]))
    for riga in righe:
        riga["celle"] = [riga[c] for c in CHIAVI]
    totali["celle"] = [totali[c] for c in CHIAVI]
    return righe, totali


def numero_csv(valore):
    return f"{valore:.2f}".replace(".", ",")


def testo_csv(righe, etichetta):
    uscita = io.StringIO()
    scrittore = csv.writer(uscita, delimiter=";")
    scrittore.writerow([etichetta, *[n for _, n in FASCE], "Totale"])
    for r in righe:
        scrittore.writerow([r["nome"], *[numero_csv(v) for v in r["celle"]], numero_csv(r["totale"])])
    return uscita.getvalue()


def voci_clienti(request):
    scadenze = (queryset(request, Scadenza).filter(pagata=False, fattura__stato=Fattura.EMESSA)
                .select_related("fattura__cliente"))
    return [(s.fattura.cliente_id, s.fattura.cliente.nome, s.data, s.residuo) for s in scadenze]


def risposta(request, voci, titolo, etichetta, nome_file, url_controparte):
    """La pagina, o il CSV e il PDF con ?formato=. url_controparte: da pk all'elenco delle sue scadenze."""
    oggi = timezone.localdate()
    righe, totali = tabella(voci, oggi)
    formato = request.GET.get("formato")
    if formato == "csv":
        esito = HttpResponse(testo_csv(righe, etichetta), content_type="text/csv; charset=utf-8")
        esito["Content-Disposition"] = f'attachment; filename="{nome_file}-{oggi:%Y%m%d}.csv"'
        return esito
    contesto = {"righe": righe, "totali": totali, "fasce": FASCE, "titolo": titolo, "etichetta": etichetta, "oggi": oggi}
    if formato == "pdf":
        html = render_to_string("fatturazione/report/scadenzario.html", {**contesto, "azienda": request.azienda})
        try:
            contenuto = report.pdf(html)
        except report.ReportNonDisponibile as e:
            messages.error(request, str(e))
            return redirect(request.path)
        esito = HttpResponse(contenuto, content_type="application/pdf")
        esito["Content-Disposition"] = f'attachment; filename="{nome_file}-{oggi:%Y%m%d}.pdf"'
        return esito
    for riga in righe:
        riga["url"] = url_controparte(riga["pk"])
    return render(request, "fatturazione/scadenzario.html", contesto)
