"""Strumenti dell'assistente: registro, contesto di esecuzione e strumenti di base."""
from .registro import Contesto, ErroreStrumento, Strumento, disponibili, esegui, registra  # noqa: F401

from . import base, scritture, viste  # noqa: F401,E402  (registrano gli strumenti di base e quelli delle viste)
