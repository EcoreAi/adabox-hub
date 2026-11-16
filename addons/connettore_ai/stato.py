"""Quando il connettore risponde e a chi: indirizzi pubblici dell'istanza, interruttori, chi può collegarsi.

Gli indirizzi vengono da SITO_URL e non dalla richiesta: l'emittente e la risorsa devono essere sempre gli stessi,
anche dietro un proxy, perché le chat li confrontano carattere per carattere."""
from django.conf import settings

AMBITO = "adabox:leggi"
PERMESSO = "connettore_ai.add_chatcollegata"


def base():
    return settings.SITO_URL.rstrip("/")


def emittente():
    """L'identificativo del server di autorizzazione: l'origine dell'istanza, senza percorso."""
    return base()


def risorsa():
    """L'indirizzo del server MCP, quello che l'utente incolla nella chat e a cui sono legati i token."""
    return base() + "/mcp"


def metadati_risorsa():
    return base() + "/.well-known/oauth-protected-resource/mcp"


def stessa_risorsa(valore):
    """`resource` può arrivare con o senza barra finale e con maiuscole nell'host: è la stessa risorsa."""
    schema, _, resto = str(valore or "").partition("://")
    host, barra, percorso = resto.partition("/")
    return f"{schema.lower()}://{host.lower()}{barra}{percorso}".rstrip("/") == risorsa()


def spento():
    """Modulo disattivato o fuori licenza, o assistente senza licenza valida: il connettore non esiste (404)."""
    from ai import licenza
    from core.registry.modules import disattivati
    return bool({"connettore_ai", "ai"} & disattivati()) or not licenza.attuale().valida


def attivo_per(azienda):
    from core import parametri
    return azienda is not None and azienda.attiva and bool(parametri.leggi("connettore_ai.attivo", azienda))


def puo_collegare(utente):
    from core.middleware import esterno
    return bool(utente and utente.is_authenticated and utente.is_active and not esterno(utente) and utente.has_perm(PERMESSO))


def aziende_collegabili(utente):
    """Le aziende della persona che hanno acceso il connettore."""
    from core import azienda
    if not puo_collegare(utente):
        return []
    return [a for a in azienda.consentite(utente) if attivo_per(a)]


def ancora_valido(collegamento):
    """A ogni chiamata e a ogni rinnovo: il token non congela né la persona né l'azienda né gli interruttori."""
    return (collegamento.attivo and not spento()
            and any(a.pk == collegamento.azienda_id for a in aziende_collegabili(collegamento.utente)))
