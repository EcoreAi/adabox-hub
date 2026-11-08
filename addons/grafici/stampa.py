"""Una pagina di Analisi in PDF, per i report pianificati del kernel (core.report_pianificati): i widget della pagina
calcolati con i permessi del proprietario, i grafici disegnati in SVG (core.svg), i KPI come numeri, le tabelle come
tabelle. Le pagine delle app e quelle condivise valgono come le vede chi ha creato il report."""
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.safestring import mark_safe

from . import motore
from .models import Pagina


def _pagina(report, request):
    if not str(report.riferimento).isdigit():
        return None
    p = Pagina.objects.filter(pk=int(report.riferimento), area__isnull=True).first()
    if p is None:
        return None
    if p.utente_id != request.user.id and not motore.condivise(request.azienda, request.user).filter(pk=p.pk).exists():
        return None
    return p


def scelte(request):
    pagine = (Pagina.objects.filter(Q(utente=request.user) | Q(pk__in=motore.condivise(request.azienda, request.user).values("pk")))
              .filter(area__isnull=True, app=""))
    return [(str(p.pk), p.titolo) for p in pagine.order_by("titolo")]


def _disegno(w):
    from core import svg
    serie = w.get("serie") or {}
    tipo = serie.get("tipo")
    if tipo in svg.DISEGNI and serie.get("righe"):
        return {"tipo": "grafico", "svg": mark_safe(svg.DISEGNI[tipo]([(str(e), float(v)) for e, v in serie["righe"]], ""))}
    if tipo == "kpi":
        return {"tipo": "kpi", "valore": serie.get("valore_testo", ""), "sotto": serie.get("periodo_testo", ""), "delta": serie.get("delta_testo", "")}
    if tipo == "tabella":
        return {"tipo": "tabella", "colonne": serie.get("colonne", []), "righe": serie.get("righe", [])[:50]}
    if w.get("tipo") == "kpi" and w.get("scheda"):
        return {"tipo": "scheda", "voci": [(k["etichetta"], k["valore"]) for k in w["scheda"].get("kpi", [])]}
    return {"tipo": "vuoto"}


def genera(report, request):
    from core import report as stampa_pdf
    p = _pagina(report, request)
    if p is None:
        from core.report_pianificati import ErroreReport
        raise ErroreReport("la pagina di Analisi non c'è più o il proprietario non la vede più")
    visibili, _ = motore.catalogo(p, request)
    widget = [{"titolo": w.get("titolo", ""), **_disegno(w)} for w in visibili]
    html = render_to_string("grafici/pagina_pdf.html", {"pagina": p, "widget": widget, "azienda": request.azienda,
                                                        "quando": timezone.localtime()})
    return f"{p.titolo}-{timezone.localdate():%Y%m%d}.pdf".replace("/", "-"), stampa_pdf.pdf(html), "application/pdf"
