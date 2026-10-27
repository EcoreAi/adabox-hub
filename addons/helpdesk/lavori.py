"""Lavori dell'helpdesk."""
from datetime import timedelta

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.utils import timezone

from core.generici import url_record

from .models import Ticket


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
