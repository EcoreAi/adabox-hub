"""Il PDF di un documento per il cliente del portale: il primo report della vista del documento (la stessa stampa
degli utenti interni), con l'azienda del documento. Chi chiama ha già controllato che il documento sia del cliente."""
from types import SimpleNamespace

from django.http import HttpResponse
from django.utils.http import content_disposition_header

from core import report
from core.viste import registry


def risposta_pdf(request, documento, nome):
    vista = registry.per_modello(type(documento))
    if vista is None or not getattr(vista, "reports", None):
        return HttpResponse("Stampa non disponibile per questo documento.", status=404)
    richiesta = SimpleNamespace(user=request.user, azienda=documento.azienda)
    try:
        dati = report.pdf(report.html(vista, richiesta, [documento], 0))
    except report.ReportNonDisponibile:
        return HttpResponse("La stampa in PDF non è disponibile in questo momento.", status=503)
    risposta = HttpResponse(dati, content_type="application/pdf")
    risposta["Content-Disposition"] = content_disposition_header(False, f"{nome}.pdf")
    return risposta
