"""Lavori dell'helpdesk."""
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.mail import get_connection, send_mail
from django.urls import reverse
from django.utils import timezone

from core import parametri
from core.generici import url_record

from .models import Ticket

SALE_VALUTAZIONE = "helpdesk.valutazione"


def link_valutazione(ticket):
    token = signing.dumps(ticket.pk, salt=SALE_VALUTAZIONE)
    return f"{settings.SITO_URL}{reverse('helpdesk:valuta', args=[token])}"


def chiedi_valutazione(ticket_id):
    """Alla chiusura: al cliente il link per dare un voto, se l'azienda lo vuole e non l'ha già dato."""
    ticket = Ticket.objects.select_related("azienda").filter(pk=ticket_id, fase__chiusa=True).first()
    if ticket is None or not ticket.email_cliente or hasattr(ticket, "valutazione"):
        return
    if not parametri.leggi("helpdesk.chiedi_valutazione", ticket.azienda):
        return
    send_mail(f"Com'è andata? {ticket.numero}",
              f"La tua richiesta «{ticket.oggetto}» è stata chiusa.\n\nCi dedichi dieci secondi? Il tuo giudizio ci "
              f"aiuta a migliorare:\n{link_valutazione(ticket)}\n", None, [ticket.email_cliente], fail_silently=True)


def avvisi_sla():
    """Ogni ora: avvisa l'assegnatario dei ticket aperti che scadono entro 2 ore o sono già scaduti (una volta)."""
    limite = timezone.now() + timedelta(hours=2)
    ticket = (Ticket.objects.filter(fase__chiusa=False, sla_avvisato=False, scadenza_sla__lte=limite)
              .exclude(assegnatario=None).exclude(assegnatario__email="").select_related("assegnatario"))
    brand = settings.THEME.get("brand", "")
    avvisati = 0
    with get_connection() as connessione:
        for t in ticket:
            scaduto = t.scadenza_sla <= timezone.now()
            send_mail(f"[{brand}] SLA {'scaduto' if scaduto else 'in scadenza'}: {t}",
                      f"Il ticket {t} {'ha superato' if scaduto else 'sta per superare'} il tempo di risposta "
                      f"({timezone.localtime(t.scadenza_sla):%d/%m/%Y %H:%M}).\n{settings.SITO_URL}{url_record(t) or ''}\n",
                      None, [t.assegnatario.email], connection=connessione)
            Ticket.objects.filter(pk=t.pk).update(sla_avvisato=True)
            avvisati += 1
    return avvisati
