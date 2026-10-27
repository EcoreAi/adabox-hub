from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect

from core import esporta, lavori

from .lista import VistaBase


class EsportaView(VistaBase):
    """GET: righe filtrate (stessi parametri della lista). POST: le righe selezionate (pk) dalla lista."""

    def get(self, request):
        return self._esporta(request, request.GET.get("formato", "xlsx"), None)

    def post(self, request):
        pks = [p for p in request.POST.getlist("pk") if p.isdigit()]
        return self._esporta(request, request.POST.get("formato", "xlsx"), pks or None)

    def _esporta(self, request, formato, pks):
        vista = self.vista
        if not vista.has_view_permission(request):
            raise PermissionDenied
        formato = formato if formato in esporta.FORMATI else "xlsx"
        qs = esporta.queryset(vista, request, pks)
        if qs.count() > settings.EXPORT_SINCRONO_MAX:
            parametri = request.GET.copy()
            parametri.pop("formato", None)
            lavori.accoda("core.esporta.in_background", modulo=vista.modulo, slug=vista.slug,
                          utente_id=request.user.pk, azienda_id=getattr(getattr(request, "azienda", None), "pk", None),
                          parametri=parametri.urlencode(), formato=formato, pks=pks, utente=request.user)
            messages.info(request, "L'esportazione è grande: la prepariamo in background e ti arriva il link per email.")
            return redirect(vista.url("lista"))
        tipo, _ = esporta.FORMATI[formato]
        risposta = HttpResponse(esporta.contenuto(vista, qs, formato), content_type=tipo)
        risposta["Content-Disposition"] = f'attachment; filename="{esporta.nome_file(vista, formato)}"'
        return risposta
