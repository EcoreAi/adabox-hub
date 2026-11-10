"""Il calendario dell'utente nei due versi (INT-01).

- dal calendario ad adabox: gli eventi cambiati diventano eventi privati dell'utente (organizzatore), senza
  promemoria (li manda già il suo calendario); i partecipanti che sono contatti dell'azienda si collegano all'evento.
- da adabox al calendario: gli eventi che l'utente organizza in adabox partono verso il suo calendario.

Come per i connettori, non si cancella nulla in nessun verso e ricorrenti e annullati non passano. L'impronta dei
campi passati (titolo, orari, luogo, descrizione) ferma i rimbalzi: ciò che arriva non riparte e ciò che parte non
torna indietro come modifica."""
import contextlib
import hashlib
import threading

from django.db import transaction
from django.db.models.functions import Lower

from core import lavori

from .fornitori.base import ErrorePosta, ErroreTemporaneo
from .models import Casella, EventoCollegato

_stato = threading.local()


@contextlib.contextmanager
def senza_eventi():
    """Ciò che si salva qui dentro arriva dal calendario esterno: non riparte."""
    prima = getattr(_stato, "muto", False)
    _stato.muto = True
    try:
        yield
    finally:
        _stato.muto = prima


def muto():
    return getattr(_stato, "muto", False)


def dati_di(evento):
    return {"titolo": evento.titolo, "inizio": evento.inizio, "fine": evento.fine, "tutto_il_giorno": evento.tutto_il_giorno,
            "luogo": evento.luogo or "", "descrizione": evento.descrizione or ""}


def impronta(d):
    if d["tutto_il_giorno"]:
        from django.utils import timezone
        quando = f"{timezone.localtime(d['inizio']).date()}|{timezone.localtime(d['fine']).date()}"
    else:
        quando = f"{d['inizio'].timestamp():.0f}|{d['fine'].timestamp():.0f}"
    testo = "\x1f".join([d["titolo"].strip(), quando, str(bool(d["tutto_il_giorno"])), d["luogo"].strip(), d["descrizione"].strip()])
    return hashlib.sha256(testo.encode()).hexdigest()


def _contatti(casella, indirizzi):
    from contatti.models import Contatto
    indirizzi = sorted({e for e in indirizzi if e and e != casella.email.lower()})
    if not indirizzi:
        return []
    return list(Contatto.objects.filter(azienda=casella.azienda).annotate(e=Lower("email")).filter(e__in=indirizzi))


def importa(casella, e):
    """Un evento del calendario esterno: 'creato', 'aggiornato', 'uguale' o 'saltato'."""
    from calendario.models import Evento
    if e["saltare"] or e["fine"] < e["inizio"]:
        return "saltato"
    nuova = impronta(e)
    legame = EventoCollegato.objects.filter(casella=casella, id_esterno=e["id"]).select_related("evento").first()
    if legame is not None and legame.impronta == nuova:
        return "uguale"
    campi = {k: e[k] for k in ("titolo", "inizio", "fine", "tutto_il_giorno", "luogo", "descrizione")}
    with senza_eventi():
        if legame is None:
            evento = Evento.objects.create(azienda=casella.azienda, organizzatore=casella.utente, privato=True, promemoria=0, **campi)
            legame = EventoCollegato(casella=casella, evento=evento, id_esterno=e["id"])
            esito = "creato"
        else:
            evento = legame.evento
            for k, v in campi.items():
                setattr(evento, k, v)
            evento.save()
            esito = "aggiornato"
        if contatti := _contatti(casella, e["partecipanti"]):
            evento.contatti.add(*contatti)
    legame.impronta = nuova
    legame.save()
    return esito


def scrivi_fuori(casella_id, evento_id):
    """Lavoro: un evento organizzato in adabox verso il calendario della casella."""
    from calendario.models import Evento

    from . import fornitori
    from .sincronia import esito
    casella = Casella.objects.select_related("utente", "azienda").filter(pk=casella_id, calendario=True).first()
    evento = Evento.objects.filter(pk=evento_id).first()
    if casella is None or evento is None or evento.organizzatore_id != casella.utente_id or evento.azienda_id != casella.azienda_id:
        return None
    dati = dati_di(evento)
    nuova = impronta(dati)
    legame = EventoCollegato.objects.filter(casella=casella, evento=evento).first()
    if legame is not None and legame.impronta == nuova:
        return "uguale"
    try:
        f = fornitori.di(casella)
        if legame is None:
            legame = EventoCollegato(casella=casella, evento=evento, id_esterno=f.crea_evento(dati))
        else:
            f.aggiorna_evento(legame.id_esterno, dati)
    except ErroreTemporaneo as err:
        esito(casella, str(err), errore=True)
        raise
    except ErrorePosta as err:
        esito(casella, f"«{evento.titolo}»: {err}", errore=True)
        return str(err)
    legame.impronta = nuova
    legame.save()
    return "scritto"


scrivi_fuori.senza_transazione = True


def evento_salvato(sender, instance, raw=False, **_):
    if raw or muto() or not instance.organizzatore_id:
        return
    caselle = list(Casella.objects.filter(utente_id=instance.organizzatore_id, azienda_id=instance.azienda_id, calendario=True)
                   .values_list("pk", flat=True))
    pk = instance.pk
    for casella_id in caselle:
        transaction.on_commit(lambda c=casella_id: lavori.accoda("posta.agenda.scrivi_fuori", casella_id=c, evento_id=pk, max_tentativi=5))
