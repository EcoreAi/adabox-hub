"""Lavori dell'helpdesk."""
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.mail import get_connection
from django.urls import reverse
from django.utils import timezone

from core import modelli_email, parametri
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
    modelli_email.messaggio("helpdesk.valutazione", ticket.azienda, {
        "numero": ticket.numero, "oggetto_ticket": ticket.oggetto, "link": link_valutazione(ticket)},
        [ticket.email_cliente]).send(fail_silently=True)


def avvisi_sla():
    """Ogni ora: avvisa l'assegnatario dei ticket aperti che scadono entro 2 ore o sono già scaduti (una volta)."""
    limite = timezone.now() + timedelta(hours=2)
    ticket = (Ticket.objects.filter(fase__chiusa=False, sla_avvisato=False, scadenza_sla__lte=limite)
              .exclude(assegnatario=None).exclude(assegnatario__email="").select_related("assegnatario", "azienda"))
    avvisati = 0
    with get_connection() as connessione:
        for t in ticket:
            scaduto = t.scadenza_sla <= timezone.now()
            modelli_email.messaggio("helpdesk.sla", t.azienda, {
                "ticket": str(t), "stato": "scaduto" if scaduto else "in scadenza",
                "azione": "ha superato" if scaduto else "sta per superare",
                "scadenza": f"{timezone.localtime(t.scadenza_sla):%d/%m/%Y %H:%M}",
                "link": f"{settings.SITO_URL}{url_record(t) or ''}"}, [t.assegnatario.email], connection=connessione).send()
            Ticket.objects.filter(pk=t.pk).update(sla_avvisato=True)
            avvisati += 1
    return avvisati
