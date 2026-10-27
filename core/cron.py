"""Pianificazioni del kernel: si sincronizzano a ogni migrate di core (le voci si aggiungono nei servizi)."""
KERNEL = []


def sincronizza(**_):
    from .lavori import sincronizza_pianificazioni
    sincronizza_pianificazioni("core", KERNEL)
