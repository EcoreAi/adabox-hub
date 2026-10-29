"""Registro degli strumenti: schema in ingresso, rischio, concorrenza, timeout, permesso. Ogni chiamata riceve
sempre un risultato (anche di errore), così la conversazione resta valida per qualunque provider."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as Scaduto
from dataclasses import dataclass, field

from django.core.exceptions import PermissionDenied

log = logging.getLogger("ai.strumenti")
LIMITE_RISULTATO = 20000                                # caratteri: oltre si tronca con un avviso


class ErroreStrumento(Exception):
    """Errore previsto (argomenti sbagliati, record inesistente...): il messaggio va al modello, senza traceback."""


@dataclass
class Strumento:
    nome: str
    descrizione: str
    schema: dict
    funzione: object                                    # funzione(contesto, **argomenti) -> str | dict | list
    rischio: str = "lettura"                            # lettura | scrittura | irreversibile
    concorrente: bool = True                            # si può eseguire in parallelo con altre letture
    timeout: float = 30.0
    permesso: str | None = None                         # "app.codename" richiesto all'utente
    app: str = ""                                       # app di appartenenza (per le chat limitate a un'app)
    # scritture: anteprima(contesto, **argomenti) -> {titolo, dettagli, riepilogo, rischio, impronta, url} valida e
    # descrive senza toccare nulla; la funzione gira solo alla conferma dell'utente (ai.proposte)
    anteprima: object = None

    def definizione(self):
        return {"nome": self.nome, "descrizione": self.descrizione, "schema": self.schema}


@dataclass
class Contesto:
    utente: object
    azienda: object = None
    conversazione: object = None
    turno: object = None
    extra: dict = field(default_factory=dict)


_registro: dict[str, Strumento] = {}


def registra(strumento):
    _registro[strumento.nome] = strumento
    return strumento


def disponibili(utente, ambito=""):
    """Gli strumenti che l'utente può usare (in ordine stabile per la cache del prefisso)."""
    return [s for _, s in sorted(_registro.items())
            if (s.permesso is None or utente.has_perm(s.permesso)) and (not ambito or not s.app or s.app == ambito)]


def _testo(valore):
    testo = valore if isinstance(valore, str) else json.dumps(valore, ensure_ascii=False, default=str)
    if len(testo) > LIMITE_RISULTATO:
        testo = testo[:LIMITE_RISULTATO] + f"\n[…risultato troncato: {len(testo)} caratteri in tutto]"
    return testo


def _proponi(strumento):
    """Una scrittura non si esegue: si salva come proposta da confermare."""
    def funzione(contesto, **argomenti):
        from .. import proposte
        return proposte.prepara(strumento, contesto, argomenti)
    return funzione


def _esegui_uno(chiamata, contesto, ammessi):
    s = ammessi.get(chiamata.nome)
    if s is None:
        return {"id": chiamata.id, "contenuto": f"Strumento «{chiamata.nome}» inesistente o non permesso.", "errore": True}
    if "_non_valido" in chiamata.argomenti:
        return {"id": chiamata.id, "contenuto": "Argomenti non validi (JSON illeggibile): riprova.", "errore": True}
    funzione = s.funzione if s.rischio == "lettura" else _proponi(s)
    try:
        if _sincroni():
            return {"id": chiamata.id, "contenuto": _testo(funzione(contesto, **chiamata.argomenti)), "errore": False}
        with ThreadPoolExecutor(max_workers=1) as esecutore:
            futuro = esecutore.submit(_con_chiusura, funzione, contesto, chiamata.argomenti)
            return {"id": chiamata.id, "contenuto": _testo(futuro.result(timeout=s.timeout)), "errore": False}
    except Scaduto:
        return {"id": chiamata.id, "contenuto": f"Lo strumento ha superato {s.timeout:g} secondi.", "errore": True}
    except ErroreStrumento as e:
        return {"id": chiamata.id, "contenuto": str(e), "errore": True}
    except PermissionDenied:
        return {"id": chiamata.id, "contenuto": "Permesso negato: l'utente non può fare questa operazione.",
                "errore": True}
    except TypeError as e:
        return {"id": chiamata.id, "contenuto": f"Argomenti non validi: {e}", "errore": True}
    except Exception as e:                              # l'errore va al modello, che può correggersi
        log.exception("strumento %s", s.nome)
        return {"id": chiamata.id, "contenuto": f"Errore: {e}", "errore": True}


def _sincroni():
    """Con AI_STRUMENTI_SINCRONI (nei test) gli strumenti girano nel thread del turno: un altro thread non vedrebbe
    la transazione del test. Niente timeout in questo modo."""
    from django.conf import settings
    return getattr(settings, "AI_STRUMENTI_SINCRONI", False)


def _con_chiusura(funzione, contesto, argomenti):
    from django.db import connection
    try:
        return funzione(contesto, **argomenti)
    finally:
        connection.close()                              # thread di lavoro: niente connessioni lasciate aperte


def esegui(chiamate, contesto, ammessi):
    """[{id, contenuto, errore}] nell'ordine delle chiamate: le letture consecutive in parallelo, le altre da sole."""
    risultati, gruppo = [], []

    def svuota():
        if not gruppo:
            return
        if len(gruppo) == 1 or _sincroni():
            risultati.extend(_esegui_uno(c, contesto, ammessi) for c in gruppo)
        else:
            with ThreadPoolExecutor(max_workers=min(8, len(gruppo))) as esecutore:
                risultati.extend(esecutore.map(lambda c: _esegui_uno(c, contesto, ammessi), gruppo))
        gruppo.clear()

    for c in chiamate:
        s = ammessi.get(c.nome)
        if s is not None and s.concorrente and s.rischio == "lettura":
            gruppo.append(c)
        else:
            svuota()
            risultati.append(_esegui_uno(c, contesto, ammessi))
    svuota()
    return risultati
