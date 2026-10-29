"""Esecuzione di una richiesta lungo la catena di un profilo: retry con backoff per gli errori temporanei e
passaggio al modello successivo, ma solo prima del primo pezzo di risposta (dopo, l'errore risale)."""
import logging
import time

from . import anthropic_api, finto, openai_compat
from .tipi import ErroreModello, Inizio

log = logging.getLogger("ai.gateway")
ADATTATORI = {"anthropic": anthropic_api.flusso, "openai_compat": openai_compat.flusso, "finto": finto.flusso}
TENTATIVI = 3
ATTESA_MASSIMA = 20.0
_dormi = time.sleep                                  # sostituibile nei test


def _attesa(errore, tentativo):
    if errore.attesa is not None:
        return min(errore.attesa, ATTESA_MASSIMA)
    return min(2.0 ** tentativo, ATTESA_MASSIMA)


def esegui(catena, protezione=None, **richiesta):
    """Generatore di pezzi (Inizio, Testo, ChiamataStrumento, Uso, Fine). `catena`: [(modello, chiave)].

    Con `protezione` (ai.protezione) la politica sui dati personali è per anello: ai modelli non locali va la
    richiesta mascherata e la risposta torna in chiaro; se la protezione non è possibile l'anello si salta.
    Senza `protezione` se ne crea una (senza conversazione): nessun chiamante la scavalca per dimenticanza."""
    if protezione is None:
        from ..protezione import Protezione
        protezione = Protezione()
    ultimo, preparate = None, {}
    for modello, chiave in catena:
        adattatore = ADATTATORI.get(modello.provider.tipo)
        if adattatore is None:
            ultimo = ErroreModello("CONFIGURAZIONE", f"tipo di provider sconosciuto: {modello.provider.tipo}")
            continue
        mascherata = protezione.serve(modello)
        try:
            if mascherata not in preparate:
                preparate[mascherata] = protezione.richiesta(richiesta, mascherata)
        except ErroreModello as e:
            ultimo = e
            log.warning("modello %s saltato: %s", modello.id_api, e)
            continue
        da_inviare = preparate[mascherata]
        for tentativo in range(TENTATIVI):
            iniziato = False
            try:
                pezzi = adattatore(modello, chiave, **da_inviare)
                if mascherata:
                    pezzi = protezione.flusso(pezzi)
                for pezzo in pezzi:
                    if not iniziato:
                        iniziato = True
                        protezione.ultima_mascherata = mascherata
                        yield Inizio(modello)
                    yield pezzo
                return
            except ErroreModello as e:
                if iniziato:
                    raise                            # risposta già partita: niente retry né fallback
                ultimo = e
                log.warning("modello %s: %s (tentativo %d)", modello.id_api, e, tentativo + 1)
                if not e.riprovabile or tentativo == TENTATIVI - 1:
                    break
                _dormi(_attesa(e, tentativo))
    raise ultimo or ErroreModello("CONFIGURAZIONE", "nessun modello nella catena")
