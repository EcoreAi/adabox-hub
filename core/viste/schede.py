"""Mattoni per le card del kanban ricco: lo stesso linguaggio in ogni modulo. L'urgenza è rossa o arancione, sempre con icona e testo."""
import datetime
from decimal import Decimal

from django.utils import timezone

from core.colori import iniziali, tinta_persona

GIORNI_URGENZA = 7
FATTO = ("verde", "icon-check")
FERMO = ("grigio", "icon-x")


def euro(valore):
    from .gruppi import numero
    return f"{numero(valore)} €"


def euro_tondi(valore):
    return f"{valore or 0:,.0f} €".replace(",", ".")


def ore(valore):
    """8.00 diventa 8, 7.50 diventa 7,5."""
    return f"{Decimal(valore).normalize():f}".replace(".", ",")


def persona(utente):
    if utente is None:
        return None
    return {"iniziali": iniziali(utente), "nome": utente.get_full_name() or utente.get_username(), "tinta": tinta_persona(utente.pk)}


def stelle(piene, testo, massimo=3):
    return (range(piene), range(massimo - piene), testo) if piene else None


def entro(data, verbo="Scade il", scaduta="Scaduta il", senza="Senza data", oggi=None):
    """(accento, icona, testo) di una data da rispettare."""
    oggi = oggi or timezone.localdate()
    if data is None:
        return "grigio", "icon-calendar", senza
    if data < oggi:
        return "rosso", "icon-alert-triangle", f"{scaduta} {data:%d/%m/%Y}"
    if data <= oggi + datetime.timedelta(days=GIORNI_URGENZA):
        return "arancio", "icon-alert-triangle", f"{verbo} {data:%d/%m/%Y}"
    return "verde", "icon-calendar", f"{verbo} {data:%d/%m/%Y}"


def scheda(esito, **altri):
    """`esito` è (accento, icona, testo); gli altri campi come in ModelView.kanban_scheda, i vuoti si tolgono."""
    return {"accento": esito[0], "scadenza": {"icona": esito[1], "testo": esito[2]}, **{k: v for k, v in altri.items() if v}}
