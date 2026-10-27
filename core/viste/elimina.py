from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import ProtectedError, RestrictedError
from django.http import HttpResponse
from django.shortcuts import redirect, render

from .lista import VistaBase, parziale, urls_di


def vai(request, url):
    """Redirect; per le richieste HTMX un HX-Redirect, così la pagina intera cambia."""
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204, headers={"HX-Redirect": url})
    return redirect(url)


class EliminaView(VistaBase):
    def _oggetto(self, request, pk):
        obj = self.vista.get_object(request, pk)
        if not self.vista.has_delete_permission(request, obj):
            raise PermissionDenied
        return obj

    def get(self, request, pk):
        vista = self.vista
        obj = self._oggetto(request, pk)
        ctx = {"vista": vista, "urls": urls_di(vista), "obj": obj, "url_elimina": vista.url("elimina", pk=pk),
               "url_annulla": vista.url("dettaglio", pk=pk)}
        return render(request, vista.template_conferma if parziale(request) else "core/vista/conferma.html", ctx)

    def post(self, request, pk):
        vista = self.vista
        obj = self._oggetto(request, pk)
        nome = str(obj)
        try:
            obj.delete()
        except (ProtectedError, RestrictedError):
            messages.error(request, f"Impossibile eliminare «{nome}»: altri dati vi fanno riferimento.")
            return vai(request, vista.url("dettaglio", pk=pk))
        messages.success(request, f"Eliminazione completata: {vista.verbose_name} «{nome}».")
        return vai(request, vista.url("lista"))
