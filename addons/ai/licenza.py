"""Licenza del modulo AI: JSON firmato Ed25519 con le chiavi fidate del kernel (le stesse dei pacchetti).

{"licenza": {"prodotto": "adabox-hub-ai", "cliente": ..., "emessa": "AAAA-MM-GG", "scadenza": "AAAA-MM-GG",
             "utenti": 25, "funzioni": ["chat", ...]}, "firma": "<base64>"}"""
import datetime
import json
from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from core.registry import pacchetti

from .models import Licenza

PRODOTTO = "adabox-hub-ai"
FUNZIONI = ["chat", "strumenti", "pianificate", "conoscenza", "specialisti"]


@dataclass
class Stato:
    valida: bool
    motivo: str = ""
    cliente: str = ""
    scadenza: datetime.date | None = None
    utenti: int = 0
    funzioni: list = field(default_factory=list)
    sviluppo: bool = False


def firma(dati, privata):
    """Il file di licenza (dict) per i dati indicati, firmato con la chiave privata di ICHNOBYTE."""
    contenuto = {"prodotto": PRODOTTO, **dati}
    return {"licenza": contenuto, "firma": pacchetti.firma(pacchetti.serializza(contenuto), privata).decode()}


def leggi(testo):
    """Stato di un file di licenza (senza salvarlo)."""
    try:
        dati = json.loads(testo)
        contenuto, segno = dati["licenza"], dati["firma"]
    except (ValueError, KeyError, TypeError):
        return Stato(False, "Il file non è una licenza leggibile.")
    if pacchetti.verifica(pacchetti.serializza(contenuto), segno, pacchetti.chiavi_fidate()) is None:
        return Stato(False, "Firma non valida o di una chiave non fidata.")
    if contenuto.get("prodotto") != PRODOTTO:
        return Stato(False, "La licenza è di un altro prodotto.")
    try:
        scadenza = datetime.date.fromisoformat(contenuto["scadenza"])
    except (KeyError, ValueError):
        return Stato(False, "La licenza non ha una scadenza valida.")
    stato = Stato(True, cliente=str(contenuto.get("cliente", "")), scadenza=scadenza,
                  utenti=int(contenuto.get("utenti") or 0), funzioni=list(contenuto.get("funzioni") or ["chat"]))
    if scadenza < timezone.localdate():
        stato.valida, stato.motivo = False, f"La licenza è scaduta il {scadenza:%d/%m/%Y}."
    return stato


def attuale():
    if getattr(settings, "AI_LICENZA_SVILUPPO", False):
        return Stato(True, cliente="Sviluppo", utenti=0, funzioni=FUNZIONI, sviluppo=True)
    ultima = Licenza.objects.first()
    if ultima is None:
        return Stato(False, "Nessuna licenza caricata.")
    return leggi(ultima.testo)
