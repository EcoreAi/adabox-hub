"""Compattazione delle conversazioni lunghe: oltre una soglia la parte già conclusa diventa un riassunto
strutturato (profilo «riassunti», modello economico) e il modello vede il riassunto più gli eventi successivi.

Il log resta in sola aggiunta: il riassunto è un evento nuovo (`riassunto`, con l'ultimo evento riassunto in
`fino_a`), niente si cancella. Si riassume solo fino al messaggio dell'utente del turno in corso escluso, così
la catena di strumenti di un turno non si spezza mai."""
import json
import logging

from django.utils import timezone

from .. import catalogo
from ..gateway import ErroreModello, Inizio, Testo, Uso, esegui as gateway
from ..models import Evento, Turno

log = logging.getLogger("ai.motore")

SOGLIA = 150_000                    # caratteri degli eventi dopo l'ultimo riassunto (~ 40.000 token)
SISTEMA = ("Riassumi la conversazione tra un utente e l'assistente di un gestionale perché l'assistente possa "
           "continuarla senza rileggerla. Scrivi in italiano, con queste sezioni:\n"
           "## Intento\nCosa vuole ottenere l'utente.\n"
           "## Dati\nFatti, numeri, nomi, record (con id e link) trovati finora: precisi, sono l'unica memoria.\n"
           "## Errori\nCosa non ha funzionato e perché.\n"
           "## In sospeso\nProposte non ancora confermate, domande senza risposta.\n"
           "## Prossimo passo\nCosa farebbe l'assistente adesso.\n"
           "Non inventare nulla; se una sezione è vuota scrivi «—».")


def _ultimo_riassunto(conversazione):
    return conversazione.eventi.filter(tipo=Evento.RIASSUNTO).order_by("-pk").first()


def messaggi(conversazione):
    """La storia per il modello: il riassunto più recente (se c'è) e gli eventi dopo di esso."""
    riassunto = _ultimo_riassunto(conversazione)
    eventi = conversazione.eventi.exclude(tipo=Evento.RIASSUNTO).order_by("pk")
    if riassunto is None:
        return [ev.dati for ev in eventi]
    dopo = [ev.dati for ev in eventi.filter(pk__gt=riassunto.dati["fino_a"])]
    prefazione = f"<riassunto della conversazione precedente>\n{riassunto.dati['testo']}\n</riassunto>\n\n"
    if dopo and dopo[0]["ruolo"] == "utente":
        dopo[0] = {**dopo[0], "testo": prefazione + dopo[0]["testo"]}
    else:
        dopo.insert(0, {"ruolo": "utente", "testo": prefazione.strip()})
    return dopo


def _trascrizione(conversazione, fino_a, riassunto):
    righe = [f"Riassunto precedente:\n{riassunto.dati['testo']}"] if riassunto else []
    eventi = conversazione.eventi.exclude(tipo=Evento.RIASSUNTO).filter(pk__lte=fino_a).order_by("pk")
    if riassunto:
        eventi = eventi.filter(pk__gt=riassunto.dati["fino_a"])
    for ev in eventi:
        d = ev.dati
        if d["ruolo"] == "utente":
            righe.append(f"UTENTE: {d['testo']}")
        elif d["ruolo"] == "assistente":
            for b in d.get("blocchi", []):
                righe.append(f"ASSISTENTE: {b['testo']}" if b["tipo"] == "testo" else
                             f"ASSISTENTE usa {b['nome']}({json.dumps(b['argomenti'], ensure_ascii=False)})")
        else:
            righe += [f"RISULTATO{' (errore)' if r.get('errore') else ''}: {r['contenuto'][:4000]}"
                      for r in d.get("risultati", [])]
    return "\n\n".join(righe)


def se_serve(turno):
    """Prima del turno: se la parte conclusa supera la soglia, la riassume. True se ha riassunto."""
    conversazione = turno.conversazione
    domanda = conversazione.eventi.filter(turno=turno, tipo=Evento.UTENTE).order_by("pk").first()
    if domanda is None:
        return False
    riassunto = _ultimo_riassunto(conversazione)
    precedenti = conversazione.eventi.exclude(tipo=Evento.RIASSUNTO).filter(pk__lt=domanda.pk)
    if riassunto:
        precedenti = precedenti.filter(pk__gt=riassunto.dati["fino_a"])
    if sum(len(json.dumps(ev.dati, ensure_ascii=False)) for ev in precedenti) < SOGLIA:
        return False
    fino_a = precedenti.order_by("-pk").values_list("pk", flat=True).first()
    lavoro = Turno.objects.create(conversazione=conversazione, utente=turno.utente, azienda=turno.azienda,
                                  compito="riassunti")
    testo, modello = [], None
    try:
        from ..protezione import Protezione
        profilo = catalogo.profilo_per("riassunti", turno.azienda, conversazione.ambito)
        for pezzo in gateway(catalogo.catena(profilo, turno.azienda), protezione=Protezione(conversazione),
                             sistema=SISTEMA, messaggi=[{"ruolo": "utente", "testo": _trascrizione(
                                 conversazione, fino_a, riassunto)[-400_000:]}], max_token=4000, effort=profilo.effort):
            if isinstance(pezzo, Inizio):
                modello = lavoro.modello = pezzo.modello
            elif isinstance(pezzo, Testo):
                testo.append(pezzo.testo)
            elif isinstance(pezzo, Uso) and modello is not None:
                lavoro.uso, lavoro.costo = pezzo.come_dict(), modello.costo(pezzo.come_dict())
    except (ErroreModello, catalogo.NessunModello) as e:
        log.warning("conversazione %s non riassunta: %s", conversazione.pk, e)
        lavoro.stato, lavoro.errore = Turno.ERRORE, str(e)
    else:
        lavoro.stato = Turno.COMPLETATO
    lavoro.testo, lavoro.finito = "".join(testo).strip(), timezone.now()
    lavoro.save()
    if lavoro.stato != Turno.COMPLETATO or not lavoro.testo:
        return False
    Evento.objects.create(conversazione=conversazione, turno=turno, tipo=Evento.RIASSUNTO,
                          dati={"ruolo": "riassunto", "testo": lavoro.testo, "fino_a": fino_a})
    return True
