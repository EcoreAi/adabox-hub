from django import template
from django.db.models import Sum

from commesse import operazioni
from commesse.models import FatturaProgetto, OreTicket
from fatturazione.models import Fattura

register = template.Library()


@register.simple_tag
def redditivita(progetto):
    return operazioni.redditivita(progetto)


@register.simple_tag
def monte_ore(contratto):
    return operazioni.monte_ore(contratto)


@register.simple_tag
def ore_del_ticket(ticket):
    voci = OreTicket.objects.filter(ticket=ticket).select_related("riga__utente").order_by("-riga__data")
    return {"voci": voci, "totale": voci.aggregate(t=Sum("riga__ore"))["t"] or 0, "contratto": operazioni.contratto_del_ticket(ticket),
            "progetto": getattr(getattr(ticket, "assistenza", None), "progetto", None)}


@register.simple_tag
def fatture_collegabili(progetto):
    """Le fatture del cliente del progetto non ancora su nessun progetto."""
    if progetto.cliente_id is None:
        return []
    legate = FatturaProgetto.objects.values("fattura")
    return Fattura.objects.filter(azienda=progetto.azienda, cliente=progetto.cliente, stato=Fattura.EMESSA).exclude(tipo=Fattura.NOTA_CREDITO).exclude(pk__in=legate)[:30]
