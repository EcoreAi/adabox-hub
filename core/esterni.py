"""Documenti gestiti da un altro sistema: si vedono in adabox ma non si modificano e non fanno partire nulla.

Un modulo (es. Connettori per gli ordini di vendita di Odoo) registra una funzione obj -> nome del sistema o None. Le
viste li mostrano in sola lettura e senza bottoni; chi crea documenti a valle (fatture, consegne) chiede
`gestito_da(obj)` e si ferma: magazzino e fatture di quei documenti restano al sistema da cui arrivano, così non si
fattura due volte allo SDI."""
import logging

log = logging.getLogger("core.esterni")
_FONTI = []


def registra(funzione):
    if funzione not in _FONTI:
        _FONTI.append(funzione)
    return funzione


def gestito_da(obj):
    """Il nome del sistema che gestisce il documento, o None. Nel dubbio (una fonte rotta) lo considera gestito fuori."""
    if obj is None or getattr(obj, "pk", None) is None:
        return None
    for funzione in _FONTI:
        try:
            if nome := funzione(obj):
                return nome
        except Exception:
            log.exception("fonte dei documenti esterni %s", getattr(funzione, "__name__", funzione))
            return "un sistema esterno"
    return None


def controlla(obj, cosa="questa operazione"):
    """ValidationError se il documento è gestito da un altro sistema."""
    from django.core.exceptions import ValidationError
    if nome := gestito_da(obj):
        raise ValidationError(f"Il documento arriva da {nome}: {cosa} si fa lì.")
