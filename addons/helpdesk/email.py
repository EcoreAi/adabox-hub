"""Ticket dalle email: il gestore del kernel per le email che non rispondono a nessun record."""
from email.utils import getaddresses

from contatti.models import Contatto
from core import chatter, parametri
from core.models import Azienda


def _indirizzi(msg):
    intestazioni = [str(v) for h in ("To", "Cc", "Delivered-To", "X-Original-To") for v in (msg.get_all(h) or [])]
    return {indirizzo.lower() for _, indirizzo in getaddresses(intestazioni)}


def apri_ticket(msg, mittente):
    """Un'email nuova all'indirizzo dell'helpdesk apre un ticket; il cliente si riconosce dall'email."""
    try:
        indirizzo = (parametri.leggi("helpdesk.indirizzo_helpdesk") or "").strip().lower()
    except KeyError:
        return None
    if not indirizzo or indirizzo not in _indirizzi(msg):
        return None
    contatto = Contatto.objects.filter(email__iexact=mittente, attivo=True).first()
    azienda = contatto.azienda if contatto else Azienda.objects.filter(attiva=True).order_by("pk").first()
    from .models import Team, Ticket
    ticket = Ticket.objects.create(azienda=azienda, oggetto=str(msg.get("Subject", "") or "(senza oggetto)")[:200],
                                   contatto=contatto, email_cliente=mittente, team=Team.objects.order_by("pk").first())
    segui_team(ticket)
    return ticket


def segui_team(ticket):
    if ticket.team_id:
        for u in ticket.team.membri.filter(is_active=True):
            chatter.segui(ticket, u)
