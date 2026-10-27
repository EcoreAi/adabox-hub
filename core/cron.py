"""Pianificazioni del kernel: si sincronizzano a ogni migrate di core (le voci si aggiungono nei servizi)."""
KERNEL = [
    {"nome": "Posta in entrata", "funzione": "core.chatter.entrata.leggi_casella", "ogni": "2m"},
]


def sincronizza(**_):
    from .lavori import sincronizza_pianificazioni
    sincronizza_pianificazioni("core", KERNEL)
