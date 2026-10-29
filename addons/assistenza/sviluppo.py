"""Dal ticket al compito di sviluppo, e ritorno: il bug diventa un compito del progetto; quando il compito arriva in
una fase chiusa il cliente riceve un messaggio sul ticket e il ticket passa alla prima fase chiusa («Risolto»)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from core import chatter
from helpdesk.models import FaseTicket, Ticket
from progetti.models import Compito

from .models import DatiTicket

PRIORITA_ALTA = {Ticket.ALTA, Ticket.URGENTE}


def crea_compito(ticket, utente):
    dati = DatiTicket.objects.select_related("progetto").get(ticket=ticket)
    if dati.progetto is None:
        raise ValueError("Il ticket non è collegato a un progetto.")
    if dati.compito_id:
        return dati.compito
    tecnici = "\n".join(f"- {k}: {v}" for k, v in dati.tecnici.items() if k != "ip")
    descrizione = "\n\n".join(p for p in (
        ticket.descrizione, f"Dati tecnici:\n{tecnici}" if tecnici else "",
        f"Dal ticket {ticket.numero} ({dati.get_tipo_display().lower()}, cliente {ticket.contatto or '—'}).") if p)
    compito = Compito.objects.create(azienda=dati.progetto.azienda, progetto=dati.progetto,
                                     titolo=f"[{ticket.numero}] {ticket.oggetto}"[:200], descrizione=descrizione,
                                     priorita=Compito.ALTA if ticket.priorita in PRIORITA_ALTA else Compito.NORMALE)
    if ticket.assegnatario_id:
        compito.assegnatari.add(ticket.assegnatario)
    dati.compito = compito
    dati.save(update_fields=["compito"])
    chatter.scrivi(ticket, utente, f"Creato il compito di sviluppo «{compito}».", tipo="nota")
    return compito


@login_required
@require_POST
def crea_compito_vista(request, pk):
    if not (request.user.has_perm("progetti.add_compito") and request.user.has_perm("helpdesk.change_ticket")):
        raise PermissionDenied
    ticket = get_object_or_404(Ticket, pk=pk)
    try:
        compito = crea_compito(ticket, request.user)
    except ValueError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Compito di sviluppo «{compito}» collegato al ticket.")
    return redirect("helpdesk:ticket_dettaglio", pk=pk)


@receiver(pre_save, sender=Compito, dispatch_uid="assistenza.compito_prima")
def _ricorda_fase(sender, instance, **_):
    instance._era_chiuso = bool(instance.pk) and Compito.objects.filter(pk=instance.pk, fase__chiusa=True).exists()


@receiver(post_save, sender=Compito, dispatch_uid="assistenza.compito_chiuso")
def compito_salvato(sender, instance, raw=False, **_):
    """Il compito è appena passato in una fase chiusa: avviso ai ticket collegati ancora aperti."""
    if raw or getattr(instance, "_era_chiuso", True) or not instance.fase.chiusa:
        return
    from .segnali import attiva
    if not attiva():
        return
    risolto = FaseTicket.objects.filter(chiusa=True).order_by("ordine", "pk").first()
    for dati in DatiTicket.objects.filter(compito=instance, ticket__fase__chiusa=False).select_related("ticket"):
        ticket = dati.ticket
        chatter.scrivi(ticket, ticket.assegnatario,
                       f"Buone notizie: la correzione per «{ticket.oggetto}» è pronta e sarà disponibile con il prossimo "
                       "rilascio. Se il problema si ripresenta rispondi pure a questo messaggio: la richiesta si riapre.")
        if risolto is not None:
            ticket.fase = risolto
            ticket.save(update_fields=["fase"])
