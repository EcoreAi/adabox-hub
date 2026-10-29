"""Strumenti dell'assistente: registro, contesto di esecuzione e strumenti di base."""
from .registro import Contesto, Strumento, disponibili, esegui, registra  # noqa: F401

from . import base  # noqa: F401,E402  (registra gli strumenti di base)
