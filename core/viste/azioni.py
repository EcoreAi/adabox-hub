from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect

from .lista import VistaBase


def _esito(request, risultato, url):
    if isinstance(risultato, HttpResponse):
        return risultato
    if risultato:
        messages.success(request, str(risultato))
    return redirect(url)


class AzioneView(VistaBase):
    """Azione di massa: POST con i pk selezionati."""
    http_method_names = ["post"]

    def post(self, request, nome):
        vista = self.vista
        if nome not in vista.actions:
            raise Http404
        metodo = getattr(vista, nome)
        if not vista.permesso_metodo(request, metodo):
            raise PermissionDenied
        pks = [p for p in request.POST.getlist("pk") if p.isdigit()]
        if not pks:
            messages.warning(request, "Nessuna riga selezionata.")
            return redirect(vista.url("lista"))
        return _esito(request, metodo(request, vista.get_queryset(request).filter(pk__in=pks)), vista.url("lista"))


class BottoneView(VistaBase):
    """Bottone nella testata del dettaglio: POST su un oggetto."""
    http_method_names = ["post"]

    def post(self, request, pk, nome):
        vista = self.vista
        if nome not in vista.buttons:
            raise Http404
        obj = vista.get_object(request, pk)
        metodo = getattr(vista, nome)
        if not vista.permesso_metodo(request, metodo):
            raise PermissionDenied
        return _esito(request, metodo(request, obj), vista.url("dettaglio", pk=obj.pk))
