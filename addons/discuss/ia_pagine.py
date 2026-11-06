"""Pannello dei riassunti, trascrizione di un vocale e pagina di una registrazione."""
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import allegati, lavori

from . import ia, servizi
from .models import Canale, Messaggio, Registrazione, Riassunto
from .pagine import PERMESSO, _canale, _messaggio_visibile, _rendi_messaggio


@login_required
@permission_required(PERMESSO, raise_exception=True)
def riassunto(request, pk):
    """Il riassunto è di chi lo chiede: legge solo ciò che quella persona può già leggere."""
    canale = _canale(request, pk)
    if not ia.disponibile(request.user):
        raise Http404
    if request.method == "POST":
        ambito = request.POST.get("ambito") if request.POST.get("ambito") in dict(ia.AMBITI) else "oggi"
        if not Riassunto.objects.filter(canale=canale, utente=request.user, stato=Riassunto.IN_CORSO).exists():
            r = Riassunto.objects.create(canale=canale, utente=request.user, ambito=ambito)
            lavori.accoda("discuss.ia.riassumi", riassunto=r.pk, max_tentativi=1)
    ultimo = Riassunto.objects.filter(canale=canale, utente=request.user).first()
    return render(request, "discuss/_pannello_riassunto.html", {"canale": canale, "r": ultimo, "ambiti": ia.AMBITI})


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def trascrivi(request, pk):
    messaggio = _messaggio_visibile(request, pk)
    if messaggio.eliminato or not ia.trascrizione_attiva():
        raise Http404
    if messaggio.trascrizione_stato != "in_corso" and not messaggio.trascrizione:
        Messaggio.objects.filter(pk=messaggio.pk).update(trascrizione_stato="in_corso")
        messaggio.trascrizione_stato = "in_corso"
        lavori.accoda("discuss.ia.trascrivi_messaggio", messaggio=messaggio.pk, max_tentativi=1)
    return _rendi_messaggio(request, messaggio)


def _registrazione(request, pk):
    r = get_object_or_404(Registrazione.objects.select_related("chiamata__canale", "avviata_da"), pk=pk)
    if not servizi.puo_vedere(request.user, r.chiamata.canale):
        raise Http404                              # chi non può stare nel canale non sa nemmeno che c'è
    return r


@login_required
@permission_required(PERMESSO, raise_exception=True)
def registrazione(request, pk):
    r = _registrazione(request, pk)
    return render(request, "discuss/registrazione.html", {
        "r": r, "canale": r.chiamata.canale, "audio": allegati.di(r).first(),
        "puo_eliminare": r.avviata_da_id == request.user.pk or servizi.puo_moderare(request.user, r.chiamata.canale)})


@login_required
@permission_required(PERMESSO, raise_exception=True)
def registrazione_audio(request, pk):
    audio = allegati.di(_registrazione(request, pk)).first()
    if audio is None:
        raise Http404
    return allegati.risposta(audio)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def registrazione_elimina(request, pk):
    r = _registrazione(request, pk)
    if r.avviata_da_id != request.user.pk and not servizi.puo_moderare(request.user, r.chiamata.canale):
        raise PermissionDenied
    canale = r.chiamata.canale_id
    allegati.di(r).delete()
    r.delete()
    return redirect("discuss:canale", pk=canale)
