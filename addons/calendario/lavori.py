"""Lavori del calendario: inviti e promemoria per email."""
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from .ics import ics
from .models import Evento


def _destinatari(evento):
    persone = list(evento.partecipanti.filter(is_active=True).exclude(email=""))
    if evento.organizzatore and evento.organizzatore.email and evento.organizzatore not in persone:
        persone.append(evento.organizzatore)
    return persone


def _quando(evento):
    inizio = timezone.localtime(evento.inizio)
    return f"{inizio:%d/%m/%Y}" if evento.tutto_il_giorno else f"{inizio:%d/%m/%Y %H:%M}"


def invia_inviti(evento_id):
    """Invito con il file .ics (METHOD:REQUEST) ai partecipanti. Restituisce il numero di email."""
    evento = Evento.objects.get(pk=evento_id)
    brand = settings.THEME.get("brand", "")
    allegato = ics(evento, "REQUEST")
    inviate = 0
    with get_connection() as connessione:
        for u in evento.partecipanti.filter(is_active=True).exclude(email=""):
            email = EmailMessage(f"[{brand}] Invito: {evento.titolo} ({_quando(evento)})",
                                 f"Sei invitato a «{evento.titolo}», {_quando(evento)}"
                                 + (f", {evento.luogo}" if evento.luogo else "") + ".\n\n" + evento.descrizione,
                                 to=[u.email], connection=connessione)
            email.attach("invito.ics", allegato, "text/calendar; method=REQUEST; charset=utf-8")
            email.send()
            inviate += 1
    return inviate


def promemoria():
    """Ogni 5 minuti: avvisa partecipanti e organizzatore degli eventi che iniziano entro il promemoria scelto."""
    adesso = timezone.now()
    # il promemoria più lungo è di un giorno: si guardano gli eventi delle prossime 24 ore
    vicini = Evento.objects.filter(promemoria__gt=0, promemoria_inviato=False, inizio__gt=adesso,
                                   inizio__lte=adesso + timedelta(days=1))
    da_avvisare = [e for e in vicini if e.inizio - timedelta(minutes=e.promemoria) <= adesso]
    brand = settings.THEME.get("brand", "")
    inviati = 0
    with get_connection() as connessione:
        for evento in da_avvisare:
            for u in _destinatari(evento):
                EmailMessage(f"[{brand}] Promemoria: {evento.titolo} ({_quando(evento)})",
                             f"«{evento.titolo}» inizia {_quando(evento)}" + (f", {evento.luogo}" if evento.luogo else "")
                             + ".", to=[u.email], connection=connessione).send()
            Evento.objects.filter(pk=evento.pk).update(promemoria_inviato=True)
            inviati += 1
    return inviati
