from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect

from core import lavori, report

from .lista import VistaBase


def _risposta(vista, request, oggetti, indice):
    contenuto = report.html(vista, request, oggetti, indice)
    if request.GET.get("html"):
        return HttpResponse(contenuto)
    try:
        dati = report.pdf(contenuto)
    except report.ReportNonDisponibile as e:
        return HttpResponse(str(e), status=503, content_type="text/plain; charset=utf-8")
    r = HttpResponse(dati, content_type="application/pdf")
    r["Content-Disposition"] = f'inline; filename="{report.nome_file(vista, indice, oggetti)}"'
    return r


def _indice(vista, indice):
    if not 0 <= indice < len(vista.reports):
        raise Http404
    return indice


class StampaView(VistaBase):
    """GET: il report di un record."""

    def get(self, request, pk, indice):
        vista = self.vista
        indice = _indice(vista, indice)
        obj = vista.get_object(request, pk)
        if not vista.has_view_permission(request, obj):
            raise PermissionDenied
        return _risposta(vista, request, [obj], indice)


class StampaMassaView(VistaBase):
    """POST con i pk selezionati nella lista: un PDF con un record per pagina (nel worker oltre la soglia)."""
    http_method_names = ["post"]

    def post(self, request, indice):
        vista = self.vista
        indice = _indice(vista, indice)
        if not vista.has_view_permission(request):
            raise PermissionDenied
        pks = [int(p) for p in request.POST.getlist("pk") if p.isdigit()]
        oggetti = list(vista.get_queryset(request).filter(pk__in=pks))
        if not oggetti:
            messages.warning(request, "Nessuna riga selezionata.")
            return redirect(vista.url("lista"))
        if len(oggetti) > settings.REPORT_SINCRONO_MAX:
            lavori.accoda("core.report.in_background", modulo=vista.modulo, slug=vista.slug, indice=indice,
                          pks=[o.pk for o in oggetti], utente_id=request.user.pk,
                          azienda_id=getattr(getattr(request, "azienda", None), "pk", None), utente=request.user)
            messages.info(request, f"Stampa di {len(oggetti)} record avviata: il PDF ti arriva per email.")
            return redirect(vista.url("lista"))
        return _risposta(vista, request, oggetti, indice)
