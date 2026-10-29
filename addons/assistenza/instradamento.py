"""Chi riceve un ticket: il team e il responsabile dell'assistenza del progetto; se il responsabile non c'è, il
membro del team con meno ticket aperti. Senza progetto: quello del cliente, se ne ha uno solo con assistenza."""
from django.db.models import Count, Q

from core import chatter

from .models import DatiTicket, Supporto


def supporto_del_cliente(contatto):
    """L'unico progetto con assistenza attiva del cliente (o della sua azienda); None se nessuno o più di uno."""
    if contatto is None:
        return None
    clienti = [contatto.pk] + ([contatto.societa_id] if contatto.societa_id else [])
    candidati = list(Supporto.objects.filter(attivo=True, progetto__cliente__in=clienti)
                     .select_related("progetto")[:2])
    return candidati[0] if len(candidati) == 1 else None


def meno_carico(team):
    membri = (team.membri.filter(is_active=True)
              .annotate(aperti=Count("ticket_assegnati", filter=Q(ticket_assegnati__fase__chiusa=False)))
              .order_by("aperti", "pk"))
    return membri.first()


def instrada(ticket, progetto=None, canale=None, tipo=None, tecnici=None, forza=False):
    """Collega il ticket al progetto (o a quello del cliente) e lo assegna. `forza` sostituisce team e assegnatario
    già presenti (canali esterni); altrimenti si riempie solo quello che manca."""
    dati, _ = DatiTicket.objects.get_or_create(ticket=ticket)
    if canale:
        dati.canale = canale
    if tipo:
        dati.tipo = tipo
    if tecnici:
        dati.tecnici = tecnici
    supporto = None
    if progetto is not None:
        dati.progetto = progetto
        supporto = Supporto.objects.filter(progetto=progetto, attivo=True).first()
    elif dati.progetto_id is None:
        supporto = supporto_del_cliente(ticket.contatto)
        if supporto is not None:
            dati.progetto = supporto.progetto
    elif dati.progetto_id:
        supporto = Supporto.objects.filter(progetto_id=dati.progetto_id, attivo=True).first()
    dati.save()
    if supporto is None:
        return dati
    campi = []
    if supporto.team_id and (forza or ticket.team_id is None):
        ticket.team = supporto.team
        campi.append("team")
    if forza or ticket.assegnatario_id is None:
        persona = supporto.responsabile or (meno_carico(supporto.team) if supporto.team_id else None)
        if persona is not None:
            ticket.assegnatario = persona
            campi.append("assegnatario")
    if campi:
        ticket.save(update_fields=campi)
    for persona in [*(supporto.team.membri.filter(is_active=True) if supporto.team_id else []),
                    *([ticket.assegnatario] if ticket.assegnatario_id else [])]:
        chatter.segui(ticket, persona)
    from .segnali import aggiorna_sla
    aggiorna_sla(ticket)
    return dati
