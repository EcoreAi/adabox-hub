from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from .lista import VistaBase, urls_di


def sezioni_form(vista, form):
    """[(titolo, [[BoundField, ...], ...])] dal layout, senza i campi in sola lettura. I campi personalizzati
    vanno dove il layout dice "@proprieta", altrimenti in una sezione "Altre informazioni" in fondo."""
    proprieta = [n for n in form.fields if n.startswith("prop_")]
    sezioni, collocati = [], False
    for titolo, righe in vista.layout():
        righe_form = []
        for riga in righe:
            if riga == ["@proprieta"]:
                righe_form.extend([form[n]] for n in proprieta)
                collocati = True
            else:
                righe_form.append([form[c] for c in riga if c in form.fields])
        sezioni.append((titolo, [r for r in righe_form if r]))
    if proprieta and not collocati:
        sezioni.append(("Altre informazioni", [[form[n]] for n in proprieta]))
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
        form_class = self.vista.get_form_class(request)
        # nuovo record: valori iniziali dalla query string (es. ?scadenza=2026-11-03 dal calendario)
        iniziali = {k: v for k, v in request.GET.items() if k in form_class.base_fields} if obj is None else {}
        return self._rendi(request, form_class(instance=obj, initial=iniziali), obj)

    def post(self, request, pk=None):
        vista = self.vista
        obj = self._oggetto(request, pk)
        form = vista.get_form_class(request)(request.POST, request.FILES, instance=obj)
        if not form.is_valid():
            return self._rendi(request, form, obj)
        nuovo = form.save(commit=False)
        vista.save_model(request, nuovo, form, change=obj is not None)
        if obj is None:
            messages.success(request, f"Creazione completata: {vista.verbose_name} «{nuovo}».")
        else:
            messages.success(request, f"Modifiche salvate: {vista.verbose_name} «{nuovo}».")
        return redirect(vista.url("dettaglio", pk=nuovo.pk))
