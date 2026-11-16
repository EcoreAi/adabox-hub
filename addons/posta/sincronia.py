"""Il giro periodico di ogni casella: prima la posta, poi il calendario. La prima volta si guarda indietro di pochi
giorni per la posta e di un mese per il calendario; poi da dove si era arrivati, con un margine per i ritardi dei
servizi (i doppioni li fermano EmailSincronizzata ed EventoCollegato)."""
import datetime
import logging

from django.db import transaction
from django.utils import timezone

from core import lavori

from . import agenda, fornitori, messaggi
from .fornitori.base import ErrorePosta, ErroreTemporaneo
from .models import Casella

log = logging.getLogger("posta.sincronia")
MARGINE = datetime.timedelta(minutes=10)
PRIMA_POSTA = datetime.timedelta(days=3)
PRIMO_CALENDARIO = datetime.timedelta(days=30)
MASSIMO_PAGINE = 30


def esito(casella, testo, errore=False):
    Casella.objects.filter(pk=casella.pk).update(ultimo_giro=timezone.now(), ultimo_esito=testo[:500], in_errore=errore)


def _posta(casella, f):
    da = (casella.cursore_posta - MARGINE) if casella.cursore_posta else timezone.now() - PRIMA_POSTA
    conti, ultimo, dopo, interni = {"scritta": 0, "gia": 0, "nessuno": 0}, casella.cursore_posta, None, messaggi.indirizzi_interni()
    tutte = []
    for _ in range(MASSIMO_PAGINE):
        voci, dopo = f.messaggi(da, dopo)
        tutte += voci
        if not dopo:
            break
    minimo = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    for voce in sorted(tutte, key=lambda v: v.get("quando") or minimo):          # Gmail elenca dal più recente: nello storico in ordine
        with transaction.atomic():
            conti[messaggi.importa(casella, voce, f, interni)] += 1
        if voce.get("quando") and (ultimo is None or voce["quando"] > ultimo):
            ultimo = voce["quando"]
    if ultimo is not None:
        Casella.objects.filter(pk=casella.pk).update(cursore_posta=ultimo)
        casella.cursore_posta = ultimo
    return conti


def _calendario(casella, f):
    da = (casella.cursore_calendario - MARGINE) if casella.cursore_calendario else timezone.now() - PRIMO_CALENDARIO
    conti, ultimo, dopo = {"creato": 0, "aggiornato": 0, "uguale": 0, "saltato": 0}, casella.cursore_calendario, None
    for _ in range(MASSIMO_PAGINE):
        voci, dopo = f.eventi(da, dopo)
        with transaction.atomic():
            for e in voci:
                conti[agenda.importa(casella, e)] += 1
                if e.get("aggiornato") and (ultimo is None or e["aggiornato"] > ultimo):
                    ultimo = e["aggiornato"]
        if ultimo is not None:
            Casella.objects.filter(pk=casella.pk).update(cursore_calendario=ultimo)
            casella.cursore_calendario = ultimo
        if not dopo:
            break
    return conti


def riassunto(posta, calendario):
    parti = []
    if posta is not None:
        parti.append(f"email con i clienti: {posta['scritta']} nuove" + (f", {posta['gia']} già presenti" if posta["gia"] else ""))
    if calendario is not None:
        parti.append(f"appuntamenti: {calendario['creato']} nuovi, {calendario['aggiornato']} aggiornati")
    return "; ".join(parti).capitalize() or "Niente da sincronizzare: posta e calendario sono spenti."


def giro(casella_id):
    """Un giro di una casella. Rilancia gli errori temporanei: ci ripensa il lavoro."""
    casella = Casella.objects.select_related("utente", "azienda").filter(pk=casella_id, utente__is_active=True).first()
    if casella is None or not (casella.posta or casella.calendario):
        return None
    try:
        f = fornitori.di(casella)
        posta = _posta(casella, f) if casella.posta else None
        calendario = _calendario(casella, f) if casella.calendario else None
    except ErroreTemporaneo as e:
        esito(casella, str(e), errore=True)
        raise
    except ErrorePosta as e:
        esito(casella, str(e), errore=True)
        return str(e)
    testo = riassunto(posta, calendario)
    esito(casella, testo)
    return testo


giro.senza_transazione = True


def giro_di_tutte():
    """Dal cron: un lavoro per casella, così una lenta o scollegata non ferma le altre."""
    for pk in Casella.objects.filter(utente__is_active=True).exclude(posta=False, calendario=False).values_list("pk", flat=True):
        lavori.accoda("posta.sincronia.giro", casella_id=pk, max_tentativi=2)
