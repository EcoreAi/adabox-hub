"""Discuss: elenco delle conversazioni, conversazione con aggiornamento periodico, invio, canali e messaggi diretti."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import allegati
from core.generici import ct_di
from core.models import Allegato

from . import notifiche, servizi
from .models import Canale, Iscrizione, Messaggio, Notifica

PERMESSO = "discuss.view_canale"


def _canale(request, pk):
    canale = get_object_or_404(Canale, pk=pk)
    if not servizi.puo_vedere(request.user, canale):
        raise Http404
    return canale


def _contesto(request, canale=None):
    utenti = get_user_model().objects.filter(is_active=True).exclude(pk=request.user.pk).order_by("username")
    iscrizioni = list(servizi.iscrizioni_di(request.user))
    return {"iscrizioni": iscrizioni, "canali": [i for i in iscrizioni if not i.canale.diretto],
            "diretti": [i for i in iscrizioni if i.canale.diretto], "corrente": canale,
            "da_scoprire": servizi.pubblici_da_scoprire(request.user), "utenti": utenti,
            "posta_non_letta": notifiche.non_lette(request.user)}


@login_required
@permission_required(PERMESSO, raise_exception=True)
def home(request):
    iscrizioni = list(servizi.iscrizioni_di(request.user)[:1])
    if iscrizioni:
        return redirect("discuss:canale", pk=iscrizioni[0].canale_id)
    return render(request, "discuss/home.html", _contesto(request))


@login_required
@permission_required(PERMESSO, raise_exception=True)
def canale(request, pk):
    canale = _canale(request, pk)
    iscrizione = servizi.iscrizione(request.user, canale)
    elenco = servizi.messaggi(canale)
    ultimo_letto = iscrizione.ultimo_letto if iscrizione else None
    if iscrizione and elenco:
        servizi.segna_letto(request.user, canale, elenco[-1].pk)
    notifiche.segna_lette_del_canale(request.user, canale)
    contesto = _contesto(request, canale)
    primo_non_letto = next((m.pk for m in elenco if ultimo_letto is not None and m.pk > ultimo_letto
                            and m.autore_id != request.user.pk), None)
    contesto.update({"canale": canale, "iscrizione": iscrizione, "messaggi": elenco, "primo_non_letto": primo_non_letto,
                     "ultimo": elenco[-1].pk if elenco else 0, "titolo": canale.titolo_per(request.user),
                     "membri": canale.membri.order_by("username"), "altro_prima": len(elenco) == servizi.PAGINA})
    return render(request, "discuss/home.html", contesto)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def nuovi(request, pk):
    """Polling: i messaggi dopo `dopo` e un nuovo poller (sostituisce il precedente)."""
    canale = _canale(request, pk)
    dopo = request.GET.get("dopo", "0")
    dopo = int(dopo) if dopo.isdigit() else 0
    elenco = servizi.messaggi(canale, dopo=dopo)
    ultimo = elenco[-1].pk if elenco else dopo
    if elenco and servizi.iscrizione(request.user, canale):
        servizi.segna_letto(request.user, canale, ultimo)
        notifiche.segna_lette_del_canale(request.user, canale)
    return render(request, "discuss/_nuovi.html", {"canale": canale, "messaggi": elenco, "ultimo": ultimo})


@login_required
@permission_required(PERMESSO, raise_exception=True)
def precedenti(request, pk):
    canale = _canale(request, pk)
    prima = request.GET.get("prima", "")
    elenco = servizi.messaggi(canale, prima=int(prima) if prima.isdigit() else None)
    return render(request, "discuss/_precedenti.html", {"canale": canale, "messaggi": elenco,
                                                        "altro_prima": len(elenco) == servizi.PAGINA})


@login_required
@permission_required("discuss.add_messaggio", raise_exception=True)
@require_POST
def invia(request, pk):
    canale = _canale(request, pk)
    if servizi.iscrizione(request.user, canale) is None:
        raise PermissionDenied                       # si scrive solo nei canali in cui si è entrati
    try:
        servizi.invia(canale, request.user, request.POST.get("corpo", ""), request.FILES.getlist("file"))
    except (ValueError, allegati.AllegatoNonValido) as e:
        if request.headers.get("HX-Request"):
            return HttpResponse(str(e), status=422)
        messages.error(request, str(e))
    if request.headers.get("HX-Request"):
        risposta = HttpResponse(status=204)
        risposta["HX-Trigger"] = "ds-nuovi"
        return risposta
    return redirect("discuss:canale", pk=canale.pk)


def _mio_messaggio(request, pk):
    messaggio = get_object_or_404(Messaggio.objects.select_related("canale", "autore"), pk=pk, eliminato=False)
    if messaggio.autore_id != request.user.pk or not servizi.puo_vedere(request.user, messaggio.canale):
        raise PermissionDenied
    return messaggio


@login_required
@permission_required(PERMESSO, raise_exception=True)
def modifica(request, pk):
    messaggio = _mio_messaggio(request, pk)
    if request.method == "POST":
        corpo = request.POST.get("corpo", "").strip()
        if corpo:
            servizi.modifica(messaggio, corpo)
        return render(request, "discuss/_messaggio.html", {"m": messaggio, "canale": messaggio.canale})
    if request.GET.get("annulla"):
        return render(request, "discuss/_messaggio.html", {"m": messaggio, "canale": messaggio.canale})
    return render(request, "discuss/_modifica.html", {"m": messaggio})


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def elimina(request, pk):
    messaggio = _mio_messaggio(request, pk)
    servizi.elimina(messaggio)
    return render(request, "discuss/_messaggio.html", {"m": messaggio, "canale": messaggio.canale})


@login_required
@permission_required(PERMESSO, raise_exception=True)
def allegato(request, pk):
    allegato = get_object_or_404(Allegato, pk=pk, content_type=ct_di(Messaggio))
    messaggio = get_object_or_404(Messaggio, pk=allegato.object_id)
    if not servizi.puo_vedere(request.user, messaggio.canale):
        raise Http404
    return allegati.risposta(allegato)


@login_required
@permission_required("discuss.add_canale", raise_exception=True)
@require_POST
def nuovo_canale(request):
    nome = request.POST.get("nome", "").strip()
    if not nome:
        messages.error(request, "Il canale ha bisogno di un nome.")
        return redirect("discuss:home")
    tipo = Canale.PRIVATO if request.POST.get("tipo") == Canale.PRIVATO else Canale.PUBBLICO
    membri = get_user_model().objects.filter(pk__in=[p for p in request.POST.getlist("membri") if p.isdigit()],
                                             is_active=True)
    canale = servizi.crea_canale(nome, tipo, request.user, membri, request.POST.get("descrizione", ""))
    return redirect("discuss:canale", pk=canale.pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def diretto(request):
    altri = list(get_user_model().objects.filter(
        pk__in=[p for p in request.POST.getlist("utenti") if p.isdigit()], is_active=True).exclude(pk=request.user.pk))
    if not altri:
        messages.error(request, "Scegli almeno una persona.")
        return redirect("discuss:home")
    return redirect("discuss:canale", pk=servizi.diretto([request.user, *altri]).pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def entra(request, pk):
    canale = _canale(request, pk)
    servizi.iscrivi(canale, request.user)
    return redirect("discuss:canale", pk=pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def esci(request, pk):
    canale = _canale(request, pk)
    if canale.diretto:
        raise PermissionDenied
    servizi.esci(canale, request.user)
    messages.success(request, f"Sei uscito da {canale.titolo_per(request.user)}.")
    return redirect("discuss:home")


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def invita(request, pk):
    canale = _canale(request, pk)
    if canale.diretto or servizi.iscrizione(request.user, canale) is None:
        raise PermissionDenied
    for u in get_user_model().objects.filter(pk__in=[p for p in request.POST.getlist("utenti") if p.isdigit()],
                                             is_active=True):
        servizi.iscrivi(canale, u)
    return redirect("discuss:canale", pk=pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def preferenze(request, pk):
    canale = _canale(request, pk)
    valore = request.POST.get("notifiche", "")
    if valore in dict(Iscrizione.NOTIFICHE):
        Iscrizione.objects.filter(canale=canale, utente=request.user).update(notifiche=valore)
    return redirect("discuss:canale", pk=pk)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def posta(request):
    """Posta in arrivo: le notifiche, prima le non lette."""
    voci = Notifica.objects.filter(utente=request.user).select_related("autore").order_by("letta", "-creata")[:200]
    contesto = _contesto(request)
    contesto.update({"voci": voci, "in_posta": True})
    return render(request, "discuss/posta.html", contesto)


@login_required
@permission_required(PERMESSO, raise_exception=True)
def apri_notifica(request, pk):
    notifica = get_object_or_404(Notifica, pk=pk, utente=request.user)
    if not notifica.letta:
        notifica.letta = True
        notifica.save(update_fields=["letta"])
    destinazione = notifica.url if notifica.url.startswith("/") and not notifica.url.startswith("//") else "/"
    return redirect(destinazione)


@login_required
@permission_required(PERMESSO, raise_exception=True)
@require_POST
def tutte_lette(request):
    Notifica.objects.filter(utente=request.user, letta=False).update(letta=True)
    return redirect("discuss:posta")


@login_required
def contatore(request):
    """La campanella in testata (aggiornata ogni 30 secondi)."""
    if not request.user.has_perm(PERMESSO):
        return HttpResponse("")
    return render(request, "discuss/_campanella.html")
