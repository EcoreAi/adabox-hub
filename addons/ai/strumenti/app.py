"""Strumenti dichiarati dalle app con la chiave "ai" del manifest (es. "calendario.ai"): un modulo dell'app che
registra i suoi Strumento con `registra`. Si caricano una volta per processo; se lo strumento non indica l'app,
diventa dell'app che lo dichiara (così le chat limitate a quell'app lo vedono)."""
import importlib
import logging

from . import registro

log = logging.getLogger("ai.strumenti")
_caricati = set()


def carica():
    from core.registry import modules
    for slug, m in modules.manifests_attivi().items():
        if not m.ai or slug in _caricati:
            continue
        _caricati.add(slug)
        prima = set(registro._registro)
        try:
            importlib.import_module(m.ai)
        except Exception:                                # un'app rotta non spegne l'assistente
            log.exception("strumenti AI di %s (%s)", slug, m.ai)
            continue
        for nome in set(registro._registro) - prima:
            registro._registro[nome].app = registro._registro[nome].app or slug
