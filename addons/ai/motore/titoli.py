"""Titolo della conversazione scritto dall'assistente dopo la prima risposta (profilo «titoli», modello economico)."""
import logging

from django.utils import timezone

from .. import catalogo
from ..gateway import ErroreModello, Inizio, Testo, Uso, esegui as gateway
from ..models import MessaggioChat, Turno
from ..protezione import Protezione

log = logging.getLogger("ai.motore")

SISTEMA = ("Scrivi il titolo di una conversazione tra un utente e l'assistente di un gestionale: al massimo sei "
           "parole, in italiano, senza virgolette né punto finale. Rispondi solo con il titolo.")


def genera(conversazione, utente, azienda=None):
    if conversazione.titolo_generato:
        return None
    messaggi = list(conversazione.messaggi.order_by("pk")[:2])
    if len(messaggi) < 2 or messaggi[1].ruolo != MessaggioChat.ASSISTENTE:
        return None
    turno = Turno.objects.create(conversazione=conversazione, utente=utente, azienda=azienda, compito="titoli")
    testo, modello = [], None
    try:
        profilo = catalogo.profilo_per("titoli", azienda, conversazione.ambito)
        richiesta = f"Domanda: {messaggi[0].testo[:1500]}\n\nRisposta: {messaggi[1].testo[:1500]}"
        for pezzo in gateway(catalogo.catena(profilo, azienda), protezione=Protezione(conversazione), sistema=SISTEMA,
                             messaggi=[{"ruolo": "utente", "testo": richiesta}], max_token=60, effort=profilo.effort):
            if isinstance(pezzo, Inizio):
                modello = turno.modello = pezzo.modello
            elif isinstance(pezzo, Testo):
                testo.append(pezzo.testo)
            elif isinstance(pezzo, Uso) and modello is not None:
                turno.uso, turno.costo = pezzo.come_dict(), modello.costo(pezzo.come_dict())
    except (ErroreModello, catalogo.NessunModello) as e:
        log.info("titolo non generato: %s", e)
        turno.stato, turno.errore = Turno.ERRORE, str(e)
    else:
        turno.stato = Turno.COMPLETATO
    turno.finito = timezone.now()
    turno.testo = "".join(testo).strip()
    turno.save()
    titolo = turno.testo.strip().strip("\"'«»“”").rstrip(".").strip()
    if turno.stato == Turno.COMPLETATO and titolo:
        conversazione.titolo, conversazione.titolo_generato = titolo[:120], True
        conversazione.save(update_fields=["titolo", "titolo_generato"])
    return titolo or None
