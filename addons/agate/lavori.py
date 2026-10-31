"""Lavori a orario: l'esito delle approvazioni in attesa, chiesto ad Agate ogni minuto.

Funziona anche senza webhook (rete che non raggiunge adabox): con lo scope `evaluate` la chiave
legge lo stato dell'approvazione della propria valutazione."""
import logging

from . import cliente
from .guardia import decisa
from .models import Collegamento, Valutazione

log = logging.getLogger("agate.lavori")


def controlla_approvazioni():
    collegamento = Collegamento.attuale()
    if collegamento is None or collegamento.modalita == Collegamento.SPENTO:
        return 0
    fatte = 0
    for valutazione in Valutazione.objects.filter(stato=Valutazione.IN_ATTESA).exclude(evaluation_id="")[:100]:
        try:
            approvazione = cliente.esito(collegamento, valutazione.evaluation_id).get("approval") or {}
        except cliente.ErroreAgate as e:
            log.warning("valutazione %s: %s", valutazione.evaluation_id, e)
            continue
        stato = approvazione.get("status")
        if stato in ("approved", "rejected", "expired"):
            decisa(valutazione, stato, approvazione.get("decided_by") or "", approvazione.get("reason") or "")
            fatte += 1
    return fatte
