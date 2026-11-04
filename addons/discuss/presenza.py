"""Chi c'è: online, assente, non disturbare, fuori ufficio, non collegato."""
import datetime

from django.utils import timezone

from .models import Presenza

ONLINE, ASSENTE, OCCUPATO, FUORI, OFFLINE = "online", "assente", "occupato", "fuori", "offline"
ETICHETTE = {ONLINE: "Online", ASSENTE: "Assente", OCCUPATO: "Non disturbare", FUORI: "Fuori ufficio", OFFLINE: "Non collegato"}
COLLEGATO_SECONDI = 90                  # la testata si fa viva ogni 30 secondi
INATTIVO_MINUTI = 10
SCRIVI_OGNI_SECONDI = 45                # per non scrivere nel database a ogni battito


def tocca(utente, attivo=True):
    """Da chiamare quando il browser si fa vivo; `attivo` se la persona ha fatto qualcosa da poco."""
    ora = timezone.now()
    p = Presenza.objects.filter(utente=utente).first()
    if p is None:
        Presenza.objects.create(utente=utente, ultimo_visto=ora, ultima_attivita=ora if attivo else None)
        return
    campi = {}
    if p.ultimo_visto is None or (ora - p.ultimo_visto).total_seconds() > SCRIVI_OGNI_SECONDI:
        campi["ultimo_visto"] = ora
    if attivo and (p.ultima_attivita is None or (ora - p.ultima_attivita).total_seconds() > SCRIVI_OGNI_SECONDI):
        campi["ultima_attivita"] = ora
    if campi:
        Presenza.objects.filter(pk=p.pk).update(**campi)


def stato_da(p, ora=None, oggi=None):
    ora, oggi = ora or timezone.now(), oggi or timezone.localdate()
    if p is None:
        return OFFLINE
    if p.fuori_fino and p.fuori_fino >= oggi:
        return FUORI
    if not p.ultimo_visto or (ora - p.ultimo_visto).total_seconds() > COLLEGATO_SECONDI:
        return OFFLINE
    if p.stato == Presenza.OCCUPATO:
        return OCCUPATO
    inattivo = not p.ultima_attivita or ora - p.ultima_attivita > datetime.timedelta(minutes=INATTIVO_MINUTI)
    return ASSENTE if p.stato == Presenza.ASSENTE or inattivo else ONLINE


def di(utenti_pk):
    """{pk utente: oggetto Presenza} per più persone, con una query sola."""
    return {p.utente_id: p for p in Presenza.objects.filter(utente_id__in=list(utenti_pk))}


def scheda(p):
    """Stato, etichetta e messaggio di una persona, come li mostrano i template."""
    stato = stato_da(p)
    etichetta = ETICHETTE[stato]
    if stato == FUORI:
        etichetta = f"Fuori ufficio fino al {p.fuori_fino:%d/%m/%Y}"
    return {"stato": stato, "etichetta": etichetta, "messaggio": p.messaggio if p else "",
            "fuori_fino": p.fuori_fino if stato == FUORI else None}


def mia(utente):
    return Presenza.objects.get_or_create(utente=utente)[0]
