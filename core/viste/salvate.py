"""Le ricerche salvate delle liste: personali o condivise con chi lavora nella stessa azienda, anche quella che si apre da sola."""
from urllib.parse import parse_qsl, urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from core.models import RicercaSalvata

from . import registry
from .interroga import id_vista


def _azienda(request):
    return getattr(request, "azienda", None)


def _ammesso(chiave):
    return chiave in ("q", "g", "o") or chiave.startswith("f_")


def pulisci(testo):
    """Solo ricerca, filtri, raggruppamento e ordine: nient'altro entra in una ricerca salvata."""
    return urlencode([(k, v) for k, v in parse_qsl(testo, keep_blank_values=False) if _ammesso(k)])[:4000]


def visibili(request, nome_vista):
    azienda = _azienda(request)
    if azienda is None:
        return RicercaSalvata.objects.none()
    return RicercaSalvata.objects.filter(Q(utente=request.user) | Q(condivisa=True), azienda=azienda, vista=nome_vista)


def predefinita(request, vista):
    azienda = _azienda(request)
    if azienda is None:
        return None
    return RicercaSalvata.objects.filter(azienda=azienda, vista=id_vista(vista), utente=request.user, predefinita=True).first()


def contesto(request, vista):
    return {"ricerche": visibili(request, id_vista(vista)).select_related("utente"), "id_vista": id_vista(vista)} if _azienda(request) else {"ricerche": [], "id_vista": ""}


def _vista(nome, request):
    modulo, _, slug = nome.partition(".")
    voce = next((v for v in registry.viste_di(modulo) if v.slug == slug), None)
    if voce is None or not voce.has_view_permission(request):
        raise Http404
    return voce


@login_required
@require_POST
def salva(request):
    vista = _vista(request.POST.get("vista", ""), request)
    azienda = _azienda(request)
    nome = request.POST.get("nome", "").strip()[:80]
    if azienda is None or not nome:
        messages.error(request, "Scrivi un nome per la ricerca." if azienda else "Scegli prima un'azienda.")
        return redirect(vista.url("lista"))
    parametri = pulisci(request.POST.get("parametri", ""))
    try:
        with transaction.atomic():
            RicercaSalvata.objects.update_or_create(azienda=azienda, utente=request.user, vista=id_vista(vista), nome=nome,
                                                    defaults={"parametri": parametri, "condivisa": request.POST.get("condivisa") == "1"})
    except IntegrityError:
        messages.error(request, "Ricerca non salvata.")
    else:
        messages.success(request, f"Ricerca «{nome}» salvata.")
    return redirect(f"{vista.url('lista')}?{parametri}" if parametri else f"{vista.url('lista')}?tutti=1")


def _mia(request, pk):
    azienda = _azienda(request)
    if azienda is None:
        raise Http404
    return get_object_or_404(RicercaSalvata, pk=pk, azienda=azienda, utente=request.user)


@login_required
@require_POST
def elimina(request, pk):
    ricerca = _mia(request, pk)
    vista = _vista(ricerca.vista, request)
    ricerca.delete()
    messages.success(request, "Ricerca eliminata.")
    return redirect(f"{vista.url('lista')}?tutti=1")


@login_required
@require_POST
def predefinita_vista(request, pk):
    """Una sola per lista e per persona; un secondo clic la toglie."""
    ricerca = _mia(request, pk)
    vista = _vista(ricerca.vista, request)
    if not vista.has_view_permission(request):
        raise PermissionDenied
    nuova = not ricerca.predefinita
    RicercaSalvata.objects.filter(azienda=ricerca.azienda, utente=request.user, vista=ricerca.vista).update(predefinita=False)
    if nuova:
        RicercaSalvata.objects.filter(pk=ricerca.pk).update(predefinita=True)
    messages.success(request, f"«{ricerca.nome}» si apre da sola." if nuova else "Si apre di nuovo la lista completa.")
    return redirect(f"{vista.url('lista')}?{ricerca.parametri}" if ricerca.parametri else f"{vista.url('lista')}?tutti=1")
