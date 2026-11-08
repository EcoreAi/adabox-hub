"""Pianificazioni del kernel: si sincronizzano a ogni migrate di core (le voci si aggiungono nei servizi)."""
KERNEL = [
    {"nome": "Posta in entrata", "funzione": "core.chatter.entrata.leggi_casella", "ogni": "2m"},
    {"nome": "Promemoria attività", "funzione": "core.attivita.promemoria", "ogni": "1d", "alle": "07:00"},
    {"nome": "Promemoria approvazioni scadute", "funzione": "core.approvazioni.promemoria", "ogni": "1d", "alle": "08:00"},
]


def sincronizza(**_):
    from django.conf import settings

    from .lavori import sincronizza_pianificazioni
    sincronizza_pianificazioni("core", [*KERNEL, {"nome": "Licenza e moduli dal portale", "funzione": "core.registry.sincronia.esegui",
                                                  "ogni": settings.LICENZA_SINCRONIA_OGNI}])
