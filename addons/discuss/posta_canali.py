"""Canali che fanno da lista email: i messaggi escono verso gli iscritti, le risposte dalla casella di ognuno rientrano."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage, get_connection
from django.urls import reverse

from core import allegati
from core.chatter import email as posta
from core.generici import ct_di
from core.models import EmailRicevuta
from core.registry import modules

from . import servizi, testo
from .models import Canale, Iscrizione, Messaggio


def indirizzo_del_canale(canale):
    """L'indirizzo di risposta del canale, se il sito ha una casella per le risposte."""
    return posta.indirizzo_risposta(ct_di(canale).pk, canale.pk)


def invia_lista(messaggio):
    """Lavoro in background: un'email a ogni iscritto che vuole ricevere qualcosa, tranne chi ha scritto."""
    m = Messaggio.objects.select_related("canale", "autore").filter(pk=messaggio, eliminato=False).first()
    if m is None or not m.canale.lista_email or "discuss" in modules.disattivati():
        return "niente da inviare"
    canale = m.canale
    risposta = indirizzo_del_canale(canale)
    link = settings.SITO_URL + reverse("discuss:canale", args=[canale.pk]) + f"?a={m.pk}"
    piede = f"\n\n—\n{'Rispondi a questa email per scrivere nel canale, o a' if risposta else 'Apri la conversazione:'} {link}"
    filo = f"<canale-{canale.pk}@{posta.host()}>"
    destinatari = (Iscrizione.objects.filter(canale=canale).exclude(notifiche=Iscrizione.NIENTE).exclude(utente=m.autore)
                   .exclude(utente__email="").filter(utente__is_active=True).select_related("utente"))
    inviate = 0
    with get_connection() as connessione:
        for i in destinatari:
            EmailMessage(f"[{canale.nome}] {testo.piano(m.corpo)[:80] or 'Nuovo messaggio'}",
                         f"{servizi.nome_di(m.autore)} ha scritto:\n\n{m.corpo}{piede}", None, [i.utente.email],
                         headers={"Message-ID": f"<ds-{m.pk}-{i.utente_id}@{posta.host()}>", "References": filo},
                         reply_to=[risposta] if risposta else None, connection=connessione).send()
            inviate += 1
    return f"email inviate: {inviate}"


def ricevi_risposta(pk, mittente, corpo, msg, riga):
    """Una risposta arrivata per email: entra nel canale solo se chi scrive è un iscritto che può scrivere."""
    canale = Canale.objects.filter(pk=pk).first()
    if canale is None:
        riga.stato, riga.motivo = EmailRicevuta.RIFIUTATA, "il canale non esiste più"
        return
    if "discuss" in modules.disattivati():
        riga.stato, riga.motivo = EmailRicevuta.RIFIUTATA, "il modulo è disattivato"
        return
    utente = next((u for u in get_user_model().objects.filter(email__iexact=mittente, is_active=True)
                   if servizi.puo_scrivere(u, canale)), None)
    if utente is None:
        riga.stato, riga.motivo = EmailRicevuta.RIFIUTATA, f"{mittente} non può scrivere in questo canale"
        return
    file, scartati = [], []
    for parte in msg.iter_attachments():
        contenuto = ContentFile(parte.get_payload(decode=True) or b"", name=parte.get_filename() or "allegato")
        try:
            allegati.valida(contenuto)
            file.append(contenuto)
        except allegati.AllegatoNonValido as e:
            scartati.append(str(e))
    if not corpo and not file:
        riga.stato, riga.motivo = EmailRicevuta.RIFIUTATA, "nessun testo né allegati"
        return
    servizi.invia(canale, utente, corpo, file)
    riga.stato, riga.motivo = EmailRicevuta.ABBINATA, "; ".join(scartati)
