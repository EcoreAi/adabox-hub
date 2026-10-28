"""Posta in arrivo: menzioni e messaggi diretti in Discuss, menzioni e messaggi nel chatter dei record seguiti.
Le menzioni e i messaggi diretti non letti arrivano anche per email (una volta sola, dopo qualche minuto)."""
import datetime

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from core import chatter
from core.generici import url_record
from core.models import Messaggio as MessaggioChatter

from . import testo
from .models import Iscrizione, Notifica

MINUTI_PRIMA_DELLA_EMAIL = 15


def _anteprima(corpo):
    corpo = " ".join((corpo or "").split())
    return corpo[:197] + "…" if len(corpo) > 200 else corpo


def da_messaggio(messaggio):
    """Una notifica per ogni iscritto interessato (menzionato, conversazione diretta, o canale seguito "tutto")."""
    from . import servizi
    canale, autore = messaggio.canale, messaggio.autore
    menzionati = {u.pk: u for u in testo.menzionati(messaggio.corpo)}
    url = f"{reverse('discuss:canale', args=[canale.pk])}#m{messaggio.pk}"
    nuove = []
    iscrizioni = {i.utente_id: i for i in Iscrizione.objects.filter(canale=canale).select_related("utente")}
    destinatari = {pk: i.utente for pk, i in iscrizioni.items()}
    destinatari.update({pk: u for pk, u in menzionati.items() if servizi.puo_vedere(u, canale)})
    for pk, utente in destinatari.items():
        if autore is not None and pk == autore.pk:
            continue
        preferenza = iscrizioni[pk].notifiche if pk in iscrizioni else Iscrizione.MENZIONI
        if preferenza == Iscrizione.NIENTE:
            continue
        if pk in menzionati:
            tipo = Notifica.MENZIONE
        elif canale.diretto:
            tipo = Notifica.DIRETTO
        elif preferenza == Iscrizione.TUTTO:
            tipo = Notifica.CANALE
        else:
            continue
        nome_autore = autore.get_full_name() or autore.username if autore else "Qualcuno"
        titolo = {Notifica.MENZIONE: f"{nome_autore} ti ha menzionato in {canale.titolo_per(utente)}",
                  Notifica.DIRETTO: f"{nome_autore} ti ha scritto",
                  Notifica.CANALE: f"{nome_autore} in {canale.titolo_per(utente)}"}[tipo]
        nuove.append(Notifica(utente=utente, tipo=tipo, autore=autore, messaggio=messaggio, titolo=titolo[:200],
                              testo=_anteprima(messaggio.corpo), url=url))
    Notifica.objects.bulk_create(nuove)


def _puo_vedere_record(utente, record):
    meta = record._meta
    return utente.is_active and utente.has_perm(f"{meta.app_label}.view_{meta.model_name}")


@receiver(post_save, sender=MessaggioChatter, dispatch_uid="discuss.chatter")
def da_chatter(sender, instance, created, raw=False, **kwargs):
    """Menzioni (in messaggi e note) e messaggi ai follower nel chatter di un record."""
    if not created or raw or instance.tipo not in (MessaggioChatter.MESSAGGIO, MessaggioChatter.NOTA):
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
    nuove = [Notifica(utente=u, tipo=tipo, autore=autore, messaggio_chatter=instance, titolo=titolo[:200],
                      testo=_anteprima(instance.corpo), url=url)
             for pk, (u, tipo, titolo) in destinatari.items() if autore is None or pk != autore.pk]
    Notifica.objects.bulk_create(nuove)


def non_lette(utente):
    return Notifica.objects.filter(utente=utente, letta=False).count()


def segna_lette_del_canale(utente, canale):
    Notifica.objects.filter(utente=utente, messaggio__canale=canale, letta=False).update(letta=True)


def invia_email():
    """Lavoro pianificato: per ogni utente, un'email con le menzioni e i messaggi diretti non letti da un po'."""
    limite = timezone.now() - datetime.timedelta(minutes=MINUTI_PRIMA_DELLA_EMAIL)
    da_avvisare = (Notifica.objects.filter(letta=False, email_inviata=False, creata__lte=limite,
                                           tipo__in=[Notifica.MENZIONE, Notifica.DIRETTO])
                   .exclude(utente__email="").select_related("utente"))
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
            send_mail(oggetto, corpo, None, [utente.email], connection=connessione)
            Notifica.objects.filter(pk__in=[n.pk for n in voci]).update(email_inviata=True)
            inviate += 1
    return f"email inviate: {inviate}"


