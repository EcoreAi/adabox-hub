"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
import datetime

from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, voce

from .models import Ticket


def voci(request, dal, oggi):
    ticket = queryset(request, Ticket).select_related("fase")
    aperti = ticket.filter(fase__chiusa=False)
    lista = reverse("helpdesk:ticket_lista")
    adesso = timezone.now()
    nuovi, miei = ticket.filter(creato__gte=dal), aperti.filter(assegnatario=request.user)
    sla_scaduti = aperti.filter(scadenza_sla__lt=adesso)
    sla_vicini = aperti.filter(scadenza_sla__gte=adesso, scadenza_sla__lt=adesso + datetime.timedelta(hours=2))
    return [
        voce(NOVITA, nuovi.count(), "ticket nuovo", "ticket nuovi", lista, dettagli=nuovi),
        voce(ATTENZIONE, miei.count(), "ticket aperto assegnato a te", "ticket aperti assegnati a te", f"{lista}?f_assegnatario={request.user.pk}", dettagli=miei),
        voce(ATTENZIONE, sla_scaduti.count(), "ticket con SLA scaduto", "ticket con SLA scaduto", lista, urgente=True, dettagli=sla_scaduti),
        voce(ATTENZIONE, sla_vicini.count(), "ticket con SLA in scadenza entro 2 ore", "ticket con SLA in scadenza entro 2 ore", lista, urgente=True, dettagli=sla_vicini),
    ]
