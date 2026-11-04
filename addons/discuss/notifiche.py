"""Posta in arrivo: menzioni e messaggi diretti in Discuss, menzioni e messaggi nel chatter dei record seguiti.
Le menzioni e i messaggi diretti non letti arrivano anche per email (una volta sola, dopo qualche minuto)."""
import datetime

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from core import chatter
from core.generici import url_record
from core.models import AttivitaPianificata
from core.models import Messaggio as MessaggioChatter
from core.registry import modules

from . import eventi, testo
from .models import ConversazioneEsterna, Iscrizione, Notifica

MINUTI_PRIMA_DELLA_EMAIL = 15


def _anteprima(corpo):
    corpo = " ".join((corpo or "").split())
    return corpo[:197] + "…" if len(corpo) > 200 else corpo


def da_messaggio(messaggio):
    """Una notifica per ogni iscritto interessato (menzionato, conversazione diretta, o canale seguito "tutto")."""
    from . import servizi
    canale, autore = messaggio.canale, messaggio.autore
    esterno = bool(messaggio.autore_esterno)
    risposta_a = messaggio.risposta_a.autore_id if messaggio.risposta_a_id else None
    # un visitatore del sito non può far suonare chi vuole scrivendo @nome
    menzionati = {} if esterno else {u.pk: u for u in testo.menzionati(messaggio.corpo)}
    url = f"{reverse('discuss:canale', args=[canale.pk])}#m{messaggio.pk}"
    nuove = []
    iscrizioni = {i.utente_id: i for i in Iscrizione.objects.filter(canale=canale).select_related("utente")}
    destinatari = {pk: i.utente for pk, i in iscrizioni.items()}
    if canale.livechat:                            # una chat assegnata disturba solo chi la segue
        assegnata = ConversazioneEsterna.objects.filter(canale=canale).values_list("assegnata_a_id", flat=True).first()
        if assegnata:
            destinatari = {pk: u for pk, u in destinatari.items() if pk == assegnata}
    destinatari.update({pk: u for pk, u in menzionati.items() if servizi.puo_vedere(u, canale)})
    for pk, utente in destinatari.items():
        if autore is not None and pk == autore.pk:
            continue
        preferenza = iscrizioni[pk].notifiche if pk in iscrizioni else Iscrizione.MENZIONI
        if preferenza == Iscrizione.NIENTE:
            continue
        if pk in menzionati:
            tipo = Notifica.MENZIONE
        elif pk == risposta_a:
            tipo = Notifica.RISPOSTA
        elif canale.diretto or canale.livechat:
            tipo = Notifica.DIRETTO
        elif preferenza == Iscrizione.TUTTO:
            tipo = Notifica.CANALE
        else:
            continue
        nome_autore = messaggio.nome_mittente if esterno or autore else "Qualcuno"
        titolo = {Notifica.MENZIONE: f"{nome_autore} ti ha menzionato in {canale.titolo_per(utente)}",
                  Notifica.RISPOSTA: f"{nome_autore} ha risposto a un tuo messaggio in {canale.titolo_per(utente)}",
                  Notifica.DIRETTO: f"{nome_autore} ti ha scritto",
                  Notifica.CANALE: f"{nome_autore} in {canale.titolo_per(utente)}"}[tipo]
        nuove.append(Notifica(utente=utente, tipo=tipo, autore=autore, messaggio=messaggio, titolo=titolo[:200],
                              testo=_anteprima(messaggio.corpo), url=url))
    Notifica.objects.bulk_create(nuove)
    for n in nuove:
        eventi.emetti("notifica", utente=n.utente, tipo_notifica=n.tipo, titolo=n.titolo, testo=n.testo, url=n.url)


def _puo_vedere_record(utente, record):
    meta = record._meta
    return utente.is_active and utente.has_perm(f"{meta.app_label}.view_{meta.model_name}")


@receiver(post_save, sender=MessaggioChatter, dispatch_uid="discuss.chatter")
def da_chatter(sender, instance, created, raw=False, **kwargs):
    """Menzioni (in messaggi e note) e messaggi ai follower nel chatter di un record."""
    if not created or raw or instance.tipo not in (MessaggioChatter.MESSAGGIO, MessaggioChatter.NOTA, MessaggioChatter.TRACCIAMENTO):
        return
    if instance.tipo == MessaggioChatter.TRACCIAMENTO and not instance.modifiche:
        return
    if "discuss" in modules.disattivati():         # modulo spento: niente si accumula in una posta che nessuno vede
        return
    record = instance.record
    if record is None:
        return
    url = url_record(record) or "/"
    autore = instance.autore
    nome_autore = (autore.get_full_name() or autore.username) if autore else (instance.autore_email or "Qualcuno")
    destinatari = {}
    for u in testo.menzionati(instance.corpo):
        if _puo_vedere_record(u, record):
            destinatari[u.pk] = (u, Notifica.MENZIONE, f"{nome_autore} ti ha menzionato su {record}")
    if instance.tipo == MessaggioChatter.MESSAGGIO:
        for u in chatter.follower_di(record):
            destinatari.setdefault(u.pk, (u, Notifica.RECORD, f"{nome_autore} su {record}"))
    corpo = instance.corpo
    if instance.tipo == MessaggioChatter.TRACCIAMENTO:         # tutto ciò che si segue finisce nella stessa posta
        for u in chatter.follower_di(record):
            destinatari.setdefault(u.pk, (u, Notifica.RECORD, f"{nome_autore} ha modificato {record}"))
        corpo = "; ".join(f"{c.get('label')}: {c.get('prima')} → {c.get('dopo')}" for c in instance.modifiche)
    nuove = [Notifica(utente=u, tipo=tipo, autore=autore, messaggio_chatter=instance, titolo=titolo[:200],
                      testo=_anteprima(corpo), url=url)
             for pk, (u, tipo, titolo) in destinatari.items() if autore is None or pk != autore.pk]
    Notifica.objects.bulk_create(nuove)
    for n in nuove:
        eventi.emetti("notifica", utente=n.utente, tipo_notifica=n.tipo, titolo=n.titolo, testo=n.testo, url=n.url)


@receiver(post_save, sender=AttivitaPianificata, dispatch_uid="discuss.attivita")
def da_attivita(sender, instance, created, raw=False, **kwargs):
    """Un'attività assegnata a qualcun altro: la trova nella posta."""
    if not created or raw or instance.assegnatario_id == instance.creato_da_id or "discuss" in modules.disattivati():
        return
    record = instance.record
    url = (url_record(record) or "/") if record is not None else "/"
    nome = (instance.creato_da.get_full_name() or instance.creato_da.username) if instance.creato_da else "Qualcuno"
    n = Notifica.objects.create(utente=instance.assegnatario, tipo=Notifica.ATTIVITA, autore=instance.creato_da,
                                titolo=f"{nome} ti ha assegnato: {instance.tipo}"[:200], url=url,
                                testo=_anteprima(f"{instance.riepilogo or record} · entro il {instance.scadenza:%d/%m/%Y}"))
    eventi.emetti("notifica", utente=n.utente, tipo_notifica=n.tipo, titolo=n.titolo, testo=n.testo, url=n.url)


def non_lette(utente):
    return Notifica.objects.filter(utente=utente, letta=False).count()


def segna_lette_del_canale(utente, canale):
    Notifica.objects.filter(utente=utente, messaggio__canale=canale, letta=False).update(letta=True)


def invia_email():
    """Lavoro pianificato: per ogni utente, un'email con le menzioni e i messaggi diretti non letti da un po'."""
    from . import posta_canali
    limite = timezone.now() - datetime.timedelta(minutes=MINUTI_PRIMA_DELLA_EMAIL)
    da_avvisare = (Notifica.objects.filter(letta=False, email_inviata=False, creata__lte=limite,
                                           tipo__in=[Notifica.MENZIONE, Notifica.DIRETTO])
                   .exclude(utente__email="").select_related("utente", "messaggio__canale"))
    per_utente = {}
    for n in da_avvisare:
        per_utente.setdefault(n.utente, []).append(n)
    inviate = 0
    with get_connection() as connessione:
        for utente, voci in per_utente.items():
            corpo = render_to_string("discuss/email/non_letti.txt", {
                "utente": utente, "voci": voci, "sito": settings.SITO_URL,
                "link": settings.SITO_URL + reverse("discuss:posta")})
            oggetto = (f"{len(voci)} messaggi per te" if len(voci) > 1 else voci[0].titolo)[:150]
            # un messaggio solo: si risponde dalla propria casella e la risposta entra nella conversazione
            canale = voci[0].messaggio.canale if len(voci) == 1 and voci[0].messaggio_id else None
            risposta = posta_canali.indirizzo_del_canale(canale) if canale is not None else None
            EmailMessage(oggetto, corpo, None, [utente.email], reply_to=[risposta] if risposta else None,
                         connection=connessione).send()
            Notifica.objects.filter(pk__in=[n.pk for n in voci]).update(email_inviata=True)
            inviate += 1
    return f"email inviate: {inviate}"


