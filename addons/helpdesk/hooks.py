"""Hook di installazione dell'Helpdesk."""
from django.contrib.auth.models import Group, User


def post_install(modulo):
    """Gruppo Operatore a tutti gli utenti attivi; numero e SLA ai ticket caricati come dati demo."""
    from .models import Ticket
    Group.objects.get(name="Helpdesk / Operatore").user_set.add(*User.objects.filter(is_active=True))
    for t in Ticket.objects.filter(numero="").order_by("pk"):
        t._priorita_caricata = None                       # forza il calcolo della scadenza SLA
        t.save()
