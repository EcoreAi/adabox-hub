"""Vista kanban: colonne dai valori di un campo (scelte o FK), card trascinabili tra le colonne."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render

from core import chatter

from . import filtri
from .lista import VistaBase, contesto_testata, urls_di


def colonne(vista, request):
    """[(valore come stringa, etichetta)] delle colonne; per le FK anche 'Senza …' se il campo ammette vuoto."""
    f = vista.opts.get_field(vista.kanban_group)
    if f.choices:
        valori = [(str(k), str(v)) for k, v in f.flatchoices]
    else:
        qs = f.related_model._default_manager.all()
        azienda = getattr(request, "azienda", None)
        if azienda is not None and any(c.name == "azienda" for c in f.related_model._meta.get_fields()):
            qs = qs.filter(azienda=azienda)
        valori = [(str(o.pk), str(o)) for o in qs[:50]]
    if f.null and not f.choices:
        valori.insert(0, ("", f"Senza {f.verbose_name}"))
    return valori


def _filtro(vista, valore):
    f = vista.opts.get_field(vista.kanban_group)
    if valore == "":
        return {f"{vista.kanban_group}__isnull": True}
    return {vista.kanban_group: valore}


class KanbanView(VistaBase):
    def get(self, request):
        vista = self.vista
        if not vista.has_view_permission(request):
            raise PermissionDenied
        qs = filtri.applica(vista, request, vista.get_queryset(request))
        cols = []
        valori = colonne(vista, request)
        for valore, etichetta in valori:
            col_qs = qs.filter(**_filtro(vista, valore))
            totale = col_qs.count()
            card = [{"obj": obj, "campi": [(vista.etichetta(c), vista.col_valore(request, obj, c)) for c in vista.kanban_fields]}
                    for obj in col_qs[:vista.kanban_limite]]
            cols.append({"valore": valore, "etichetta": etichetta, "totale": totale, "card": card,
                         "altri": totale - len(card)})
        testata = contesto_testata(request, vista, "kanban")
        return render(request, vista.template_kanban, {
            "vista": vista, "urls": urls_di(vista), "colonne": cols, "tutte": valori,
            "filtri": filtri.specifiche(vista, request), "puo_aggiungere": vista.has_add_permission(request),
            "puo_spostare": vista.has_change_permission(request), "campo": vista.kanban_group, "extra_get": [],
            **testata})


class SpostaView(VistaBase):
    """Cambia il valore del campo di raggruppamento (colonna) di un record: permesso change, tracciamento."""
    http_method_names = ["post"]

    def post(self, request, pk):
        vista = self.vista
        obj = vista.get_object(request, pk)
        if not vista.has_change_permission(request, obj):
            raise PermissionDenied
        valore = request.POST.get("valore", "")
        if valore not in dict(colonne(vista, request)):
            return HttpResponseBadRequest("colonna non valida")
        campo = vista.opts.get_field(vista.kanban_group)
        tracciati = list(vista.tracked_fields) if vista.chatter else []
        vecchi = chatter.valori(obj, tracciati) if tracciati else None
        if campo.choices:
            setattr(obj, campo.name, valore)
        else:
            setattr(obj, campo.attname, int(valore) if valore else None)
        if motivo := vista.kanban_vietato(request, obj):
            if request.headers.get("HX-Request"):
                return HttpResponse(motivo, status=409, content_type="text/plain; charset=utf-8")
            messages.error(request, motivo)
            return redirect(vista.url("kanban"))
        obj.save(update_fields=[campo.name])
        if vecchi is not None:
            chatter.traccia(obj, vecchi, request.user)
        if request.headers.get("HX-Request"):
            return HttpResponse(status=204)
        messages.success(request, f"«{obj}» spostato.")
        return redirect(vista.url("kanban") + (f"?{request.POST['ritorno']}" if request.POST.get("ritorno") else ""))
