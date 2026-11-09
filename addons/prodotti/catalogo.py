"""Catalogo in PDF: i prodotti scelti a griglia, per categoria, con foto e prezzo."""
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone

from core import report


def html(request, prodotti, mostra_prezzi=True):
    azienda = getattr(request, "azienda", None)
    logo = Path(settings.MEDIA_ROOT, azienda.logo.name).resolve().as_uri() if azienda is not None and azienda.logo else ""
    prodotti = list(prodotti.select_related("categoria", "aliquota_iva").prefetch_related("immagini")
                    .order_by("categoria__nome", "nome"))
    return render_to_string("prodotti/report/catalogo.html", {
        "report": {"nome": "Catalogo"}, "titolo": "Catalogo prodotti", "oggetti": [None], "prodotti": prodotti,
        "mostra_prezzi": mostra_prezzi, "azienda": azienda, "logo": logo, "oggi": timezone.localdate(),
        "utente": request.user, "theme": settings.THEME, "modello": None, "css_modello": ""})


def risposta(request, prodotti):
    contenuto = html(request, prodotti)
    if request.GET.get("html"):
        return HttpResponse(contenuto)
    try:
        dati = report.pdf(contenuto)
    except report.ReportNonDisponibile as e:
        return HttpResponse(str(e), status=503, content_type="text/plain; charset=utf-8")
    r = HttpResponse(dati, content_type="application/pdf")
    r["Content-Disposition"] = f'inline; filename="catalogo-{timezone.localtime():%Y%m%d}.pdf"'
    return r
