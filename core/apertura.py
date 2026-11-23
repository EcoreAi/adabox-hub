"""Dove si apre l'app installata: la scelta della persona nel profilo, o la scorciatoia dell'icona (?apri=)."""
from django.urls import NoReverseMatch, reverse

DESTINAZIONI = {"parla": ("ai:parla", "ai.add_conversazione"), "chat": ("ai:chat", "ai.add_conversazione")}


def destinazione(utente, scelta):
    """L'indirizzo della pagina scelta, se esiste (modulo installato) e la persona la può usare; None altrimenti."""
    voce = DESTINAZIONI.get(scelta or "")
    if voce is None or not utente.has_perm(voce[1]):
        return None
    try:
        return reverse(voce[0])
    except NoReverseMatch:
        return None
