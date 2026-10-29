"""Collegamenti dell'assistenza: ticket nuovi instradati, scadenze dal contratto, prima risposta, ticket da email."""
from django.db import connection
from django.db.models.signals import post_save
from django.dispatch import receiver

from contatti.models import Contatto  # noqa: F401  (l'helpdesk dipende da contatti)
from core.models import Messaggio
from helpdesk.models import Ticket
from helpdesk.segnali import ticket_da_email

from .models import Contratto, DatiTicket, Supporto

_pronte = False


def attiva():
    """Le tabelle esistono (il modulo può essere caricato prima delle sue migrazioni, es. mentre si installano le
    dipendenze) e il modulo non è disattivato. Una volta trovate, le tabelle non si cercano più."""
    global _pronte
    if not _pronte:
        _pronte = DatiTicket._meta.db_table in connection.introspection.table_names()
        if not _pronte:
            return False
    from core.registry.modules import disattivati
    return "assistenza" not in disattivati()


def aggiorna_sla(ticket):
    """Scadenze del contratto del progetto (o del cliente): prima risposta e risoluzione (quella che l'helpdesk
    segue e avvisa). Senza contratto restano le ore dell'helpdesk."""
    dati = DatiTicket.objects.filter(ticket=ticket).select_related("progetto").first()
    supporto = Supporto.objects.filter(progetto_id=dati.progetto_id).first() if dati and dati.progetto_id else None
    contratto = supporto.contratto_valido() if supporto else Contratto.valido_per(ticket.contatto)
    if contratto is None:
        return
    from .sla import scadenze
    risposta, risoluzione = scadenze(ticket, contratto)
    if dati is None:
        dati = DatiTicket.objects.create(ticket=ticket)
    DatiTicket.objects.filter(pk=dati.pk).update(scadenza_risposta=risposta)
    if ticket.scadenza_sla != risoluzione:
        Ticket.objects.filter(pk=ticket.pk).update(scadenza_sla=risoluzione, sla_avvisato=False)
        ticket.scadenza_sla = risoluzione


@receiver(post_save, sender=Ticket, dispatch_uid="assistenza.ticket_salvato")
def ticket_salvato(sender, instance, created, raw=False, **_):
    if raw or not attiva():
        return
    if created:
        from .instradamento import instrada
        instrada(instance)                              # riempie progetto, team e assegnatario se mancano
    elif instance.priorita != getattr(instance, "_priorita_caricata", instance.priorita):
        aggiorna_sla(instance)                          # cambiata la priorità: scadenze ricalcolate


@receiver(ticket_da_email, dispatch_uid="assistenza.ticket_da_email")
def da_email(sender, ticket, **_):
    if not attiva():
        return
    from .instradamento import instrada
    instrada(ticket, canale=DatiTicket.EMAIL)


@receiver(post_save, sender=Messaggio, dispatch_uid="assistenza.prima_risposta")
def prima_risposta(sender, instance, created, raw=False, **_):
    """Il primo messaggio pubblico di un utente interno su un ticket è la prima risposta."""
    if not created or raw or instance.tipo != Messaggio.MESSAGGIO or instance.autore_id is None or not attiva():
        return
    from django.contrib.contenttypes.models import ContentType

    from core.middleware import esterno
    if instance.content_type_id != ContentType.objects.get_for_model(Ticket).pk or esterno(instance.autore):
        return
    DatiTicket.objects.filter(ticket_id=instance.object_id, risposta_il__isnull=True).update(
        risposta_il=instance.creato)
