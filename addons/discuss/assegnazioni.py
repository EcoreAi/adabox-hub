"""Chi segue una chat con un cliente: la prende chi è libero, la riceve l'operatore con meno lavoro, o la assegna un collega."""
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from . import eventi, presenza, servizi
from .models import Canale, ConversazioneEsterna, Evento, Iscrizione, Notifica, Sportello


def _avvisa_barra(canale):
    for pk in canale.iscrizioni.values_list("utente_id", flat=True):
        Evento.objects.create(tipo="barra", utente_id=pk)


def assegna(conv, utente, da=None):
    """Assegna la chat, o la libera con `utente` vuoto. Lo dice nella conversazione e avvisa chi la riceve."""
    prima = conv.assegnata_a_id
    nuovo = utente.pk if utente else None
    if prima == nuovo:
        return
    ConversazioneEsterna.objects.filter(pk=conv.pk).update(assegnata_a=utente)
    conv.assegnata_a = utente
    if utente is not None:
        servizi.iscrivi(conv.canale, utente, 0, ruolo=Iscrizione.MODERATORE)
    nome_da = servizi.nome_di(da) if da else ""
    if utente is None:
        testo = f"{nome_da} ha lasciato la chat"
    elif da is None:
        testo = f"Chat assegnata a {servizi.nome_di(utente)}"
    elif da.pk == utente.pk:
        testo = f"{nome_da} ha preso in carico la chat"
    else:
        testo = f"{nome_da} ha assegnato la chat a {servizi.nome_di(utente)}"
    servizi.avviso(conv.canale, da, testo)
    if utente is not None and (da is None or da.pk != utente.pk):
        n = Notifica.objects.create(utente=utente, tipo=Notifica.DIRETTO, autore=da, titolo=f"Ti è stata assegnata la chat di {conv.nome}"[:200],
                                    url=f"/discuss/c/{conv.canale_id}/")
        eventi.emetti("notifica", utente=utente, tipo_notifica=n.tipo, titolo=n.titolo, testo="", url=n.url)
    _avvisa_barra(conv.canale)


def scegli_operatore(sportello):
    """Tra chi è collegato e non ha chiesto di non essere disturbato, chi ha meno chat aperte; a parità, il primo."""
    operatori = list(sportello.operatori.filter(is_active=True).annotate(
        aperte=Count("chat_assegnate", filter=Q(chat_assegnate__sportello=sportello, chat_assegnate__chiusa__isnull=True))).order_by("aperte", "pk"))
    stati = presenza.di(u.pk for u in operatori)
    return next((u for u in operatori if presenza.stato_da(stati.get(u.pk)) == presenza.ONLINE), None)


def a_turno(conv):
    """Se lo sportello distribuisce da solo e la chat è libera: a chi tocca. Se non c'è nessuno, resta da prendere."""
    if conv.assegnata_a_id:
        return conv.assegnata_a
    if conv.sportello.distribuzione != Sportello.A_TURNO:
        return None
    scelto = scegli_operatore(conv.sportello)
    if scelto is not None:
        assegna(conv, scelto)
    return scelto


def chi_scrive_la_prende(canale, autore):
    """Chi risponde a una chat libera se ne occupa: gli altri non devono rispondere anche loro."""
    if autore is None:
        return
    conv = ConversazioneEsterna.objects.select_related("canale").filter(canale=canale, assegnata_a__isnull=True, chiusa__isnull=True).first()
    if conv is not None:
        assegna(conv, autore, da=autore)


def operatori_di(canale):
    if not canale.livechat:
        return []
    conv = ConversazioneEsterna.objects.filter(canale=canale).select_related("sportello").first()
    return list(conv.sportello.operatori.filter(is_active=True).order_by("first_name", "username")) if conv else []


@login_required
@require_POST
def vista(request, pk):
    """Prendere, assegnare a un collega dello sportello, lasciare. Solo per chi sta già nella conversazione."""
    canale = get_object_or_404(Canale, pk=pk, livechat=True)
    if not request.user.has_perm("discuss.view_canale") or servizi.iscrizione(request.user, canale) is None:
        raise Http404
    conv = get_object_or_404(ConversazioneEsterna.objects.select_related("canale", "sportello"), canale=canale)
    valore = request.POST.get("utente", "")
    if valore == "0":
        assegna(conv, None, da=request.user)
    elif valore.isdigit():
        if int(valore) != request.user.pk and not conv.sportello.operatori.filter(pk=valore, is_active=True).exists():
            raise PermissionDenied
        utente = get_object_or_404(get_user_model(), pk=valore, is_active=True)
        if utente.pk == request.user.pk or conv.sportello.operatori.filter(pk=utente.pk).exists():
            assegna(conv, utente, da=request.user)
    return redirect("discuss:canale", pk=pk)
