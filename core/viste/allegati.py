from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from core import allegati
from core.generici import ct_di, vista_e_oggetto
from core.models import Allegato


def _elenco(request, vista, obj):
    return render(request, "core/allegati/_elenco.html", {
        "obj": obj, "ct": ct_di(obj).pk, "allegati": allegati.di(obj),
        "puo_modificare": vista.has_change_permission(request, obj)})


@require_GET
@login_required
def elenco(request, ct, pk):
    vista, obj = vista_e_oggetto(request, ct, pk, "view")
    return _elenco(request, vista, obj)


@require_POST
@login_required
def carica(request, ct, pk):
    vista, obj = vista_e_oggetto(request, ct, pk, "change")
    for file in request.FILES.getlist("file"):
        try:
            allegati.salva(obj, file, request.user)
        except allegati.AllegatoNonValido as e:
            messages.error(request, str(e))
    if request.headers.get("HX-Request"):
        return _elenco(request, vista, obj)
    return redirect(vista.url("dettaglio", pk=obj.pk))


@require_GET
@login_required
def scarica(request, pk):
    allegato = get_object_or_404(Allegato, pk=pk)
    vista_e_oggetto(request, allegato.content_type_id, allegato.object_id, "view")
    return allegati.risposta(allegato)


@require_POST
@login_required
def elimina(request, pk):
    allegato = get_object_or_404(Allegato, pk=pk)
    vista, obj = vista_e_oggetto(request, allegato.content_type_id, allegato.object_id, "change")
    allegato.file.delete(save=False)
    allegato.delete()
    if request.headers.get("HX-Request"):
        return _elenco(request, vista, obj)
    return redirect(vista.url("dettaglio", pk=obj.pk))
