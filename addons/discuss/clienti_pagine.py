"""Le azioni dell'operatore sul cliente di una chat: collega, scollega, cerca, crea. Serve essere nella conversazione
e poter vedere i contatti; il contatto si cerca sempre nell'azienda corrente, con le regole della sua lista."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import chatter, sequenze
from core.dashboard import queryset

from . import clienti, servizi
from .models import Canale, ConversazioneEsterna


def _conversazione(request, pk):
    canale = get_object_or_404(Canale, pk=pk, livechat=True)
    if not request.user.has_perm("discuss.view_canale") or servizi.iscrizione(request.user, canale) is None or not clienti.attivi():
        raise Http404
    conv = ConversazioneEsterna.objects.select_related("sportello", "connessione").filter(canale=canale).first()
    if conv is None:
        raise Http404
    if not request.user.has_perm("contatti.view_contatto"):
        raise PermissionDenied
    azienda_sportello = conv.sportello.azienda_id
    if azienda_sportello is not None and azienda_sportello != getattr(request.azienda, "pk", None):
        raise PermissionDenied                         # la chat è di un'altra azienda: si passa prima a quella
    return conv


def _contatti(request):
    from contatti.models import Contatto
    return queryset(request, Contatto)


@login_required
def cerca(request, pk):
    _conversazione(request, pk)
    testo = request.GET.get("q", "").strip()[:80]
    risultati = []
    if len(testo) >= 2:
        risultati = list(_contatti(request).filter(Q(nome__icontains=testo) | Q(email__icontains=testo) | Q(codice__iexact=testo)
                                                   | Q(telefono__icontains=testo) | Q(cellulare__icontains=testo))[:clienti.MASSIMO_CERCA])
    return render(request, "discuss/_clienti_risultati.html", {"risultati": risultati, "canale_pk": pk, "q": testo})


@login_required
@require_POST
def collega(request, pk):
    conv = _conversazione(request, pk)
    contatto = get_object_or_404(_contatti(request), pk=request.POST.get("contatto") or 0)
    clienti.collega(conv, contatto)
    messages.success(request, f"Chat collegata a {contatto}.")
    return redirect("discuss:canale", pk=pk)


@login_required
@require_POST
def scollega(request, pk):
    clienti.scollega(_conversazione(request, pk))
    messages.success(request, "Chat scollegata dal contatto.")
    return redirect("discuss:canale", pk=pk)


@login_required
@require_POST
def crea(request, pk):
    conv = _conversazione(request, pk)
    if not request.user.has_perm("contatti.add_contatto") or request.azienda is None:
        raise PermissionDenied
    from contatti.models import Contatto
    contatto = Contatto.objects.create(azienda=request.azienda, codice=sequenze.prossimo("contatti.contatto", request.azienda),
                                       **clienti.dati_nuovo_contatto(conv))
    chatter.scrivi(contatto, request.user, f"Contatto creato da una chat di {conv.sportello.nome}.", tipo="sistema")
    clienti.collega(conv, contatto)
    messages.success(request, f"Contatto {contatto} creato e collegato.")
    return redirect("discuss:canale", pk=pk)
