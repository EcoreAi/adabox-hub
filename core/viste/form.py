from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from .lista import VistaBase, urls_di


def sezioni_form(vista, form):
    """[(titolo, [[BoundField, ...], ...])] dal layout, senza i campi in sola lettura."""
    sezioni = []
    for titolo, righe in vista.layout():
        righe_form = [[form[c] for c in riga if c in form.fields] for riga in righe]
        sezioni.append((titolo, [r for r in righe_form if r]))
    return sezioni


class FormView(VistaBase):
    """Nuovo (senza pk) e modifica (con pk)."""

    def _oggetto(self, request, pk):
        vista = self.vista
        if pk is None:
            if not vista.has_add_permission(request):
                raise PermissionDenied
            return None
        obj = vista.get_object(request, pk)
        if not vista.has_change_permission(request, obj):
            raise PermissionDenied
        return obj

    def _rendi(self, request, form, obj):
        vista = self.vista
        return render(request, vista.template_form, {
            "vista": vista, "urls": urls_di(vista), "form": form, "obj": obj,
            "sezioni": sezioni_form(vista, form),
            "annulla": vista.url("dettaglio", pk=obj.pk) if obj else vista.url("lista"),
        })

    def get(self, request, pk=None):
        obj = self._oggetto(request, pk)
        return self._rendi(request, self.vista.get_form_class()(instance=obj), obj)

    def post(self, request, pk=None):
        vista = self.vista
        obj = self._oggetto(request, pk)
        form = vista.get_form_class()(request.POST, request.FILES, instance=obj)
        if not form.is_valid():
            return self._rendi(request, form, obj)
        nuovo = form.save(commit=False)
        vista.save_model(request, nuovo, form, change=obj is not None)
        if obj is None:
            messages.success(request, f"Creazione completata: {vista.verbose_name} «{nuovo}».")
        else:
            messages.success(request, f"Modifiche salvate: {vista.verbose_name} «{nuovo}».")
        return redirect(vista.url("dettaglio", pk=nuovo.pk))
