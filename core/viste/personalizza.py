"""Personalizzazione delle viste per richiesta (es. dall'app Studio), senza toccare la ModelView registrata.

Un modulo registra `funzione(vista, request) -> {attributo: valore}`; all'inizio di ogni richiesta la vista è
sostituita da una copia superficiale con gli attributi sovrascritti (solo quelli di ATTRIBUTI)."""
import copy
import logging

log = logging.getLogger(__name__)

ATTRIBUTI = frozenset({"list_display", "list_filter", "search_fields", "list_group_by", "list_sum", "ordering",
                       "per_page", "form_layout", "kanban_fields", "etichette"})

_funzioni = []


def registra(funzione):
    if funzione not in _funzioni:
        _funzioni.append(funzione)
    return funzione


def rimuovi(funzione):
    if funzione in _funzioni:
        _funzioni.remove(funzione)


def sovrascritture(vista, request):
    risultato = {}
    for funzione in _funzioni:
        try:
            valori = funzione(vista, request) or {}
        except Exception:                                # una personalizzazione rotta non blocca la vista
            log.exception("personalizzazione %r fallita per %r", funzione, vista)
            continue
        risultato.update({k: v for k, v in valori.items() if k in ATTRIBUTI})
    return risultato


def applica(vista, request):
    valori = sovrascritture(vista, request)
    if not valori:
        return vista
    copia = copy.copy(vista)
    for attributo, valore in valori.items():
        setattr(copia, attributo, valore)
    copia.originale = getattr(vista, "originale", vista)
    return copia
