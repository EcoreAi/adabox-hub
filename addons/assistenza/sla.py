"""Scadenze SLA dal contratto del cliente: ore lavorative (giorni e fascia oraria della politica) o 24 ore."""
import datetime

from django.utils import timezone

MAX_GIORNI = 400                       # rete di sicurezza: una politica senza giorni lavorativi non gira all'infinito


def aggiungi_ore(partenza, ore, politica):
    """Il momento che si raggiunge contando `ore` dalla `partenza` secondo la politica."""
    if not politica.ore_lavorative:
        return partenza + datetime.timedelta(hours=ore)
    giorni = politica.elenco_giorni() or {0, 1, 2, 3, 4}
    resto = datetime.timedelta(hours=ore)
    adesso = timezone.localtime(partenza)
    for _ in range(MAX_GIORNI):
        if adesso.weekday() in giorni:
            inizio = adesso.replace(hour=politica.inizio_giornata.hour, minute=politica.inizio_giornata.minute,
                                    second=0, microsecond=0)
            fine = adesso.replace(hour=politica.fine_giornata.hour, minute=politica.fine_giornata.minute,
                                  second=0, microsecond=0)
            da = max(adesso, inizio)
            if da < fine:
                disponibile = fine - da
                if resto <= disponibile:
                    return da + resto
                resto -= disponibile
        domani = (adesso + datetime.timedelta(days=1)).date()
        adesso = timezone.make_aware(datetime.datetime.combine(domani, datetime.time(0, 0)))
    return partenza + datetime.timedelta(hours=ore)


def scadenze(ticket, contratto):
    """(scadenza della prima risposta, scadenza di risoluzione) del ticket secondo il contratto."""
    politica = contratto.politica
    partenza = ticket.creato or timezone.now()
    return (aggiungi_ore(partenza, politica.ore("risposta", ticket.priorita), politica),
            aggiungi_ore(partenza, politica.ore("risoluzione", ticket.priorita), politica))
