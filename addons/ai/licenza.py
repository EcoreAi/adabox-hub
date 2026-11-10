"""Licenza del modulo AI: JSON firmato Ed25519 con le chiavi fidate del kernel (le stesse dei pacchetti).

{"licenza": {"prodotto": "adabox-hub-ai", "cliente": ..., "emessa": "AAAA-MM-GG", "scadenza": "AAAA-MM-GG",
             "utenti": 25, "funzioni": ["ricerca_web", "memoria", ...]}, "firma": "<base64>"}

"funzioni" sono le chiavi del catalogo nel manifest (core.funzioni); senza, le comprende tutte. Le licenze emesse
prima del catalogo avevano ["chat", "strumenti", ...], di cui contava solo "chat": valgono come tutte. Senza una
licenza propria valgono le funzioni dell'assistente nella licenza dell'istanza."""
import datetime
import json
from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from core import licenza as licenza_istanza
from core.registry import pacchetti

from .models import Licenza

PRODOTTO = "adabox-hub-ai"
VECCHIO_FORMATO = {"chat", "strumenti"}                 # chiavi delle licenze emesse prima del catalogo


@dataclass
class Stato:
    valida: bool
    motivo: str = ""
    cliente: str = ""
    scadenza: datetime.date | None = None
    utenti: int = 0
    funzioni: frozenset | None = None                   # chiavi comprese; None = tutte
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
                  utenti=int(contenuto.get("utenti") or 0), funzioni=_funzioni(contenuto.get("funzioni")))
    if scadenza < timezone.localdate():
        stato.valida, stato.motivo = False, f"La licenza è scaduta il {scadenza:%d/%m/%Y}."
    return stato


def _funzioni(lista):
    if not isinstance(lista, list) or VECCHIO_FORMATO & set(lista):
        return None
    return frozenset(f for f in lista if isinstance(f, str))


def comprese():
    """Le funzioni dell'assistente comprese (fonte di core.funzioni per "ai"); None = tutte. Senza licenza valida
    l'assistente è spento per intero, e non serve nascondere le singole parti."""
    stato = attuale()
    return stato.funzioni if stato.valida else None


def attuale():
    if getattr(settings, "AI_LICENZA_SVILUPPO", False):
        return Stato(True, cliente="Sviluppo", utenti=0, sviluppo=True)
    ultima = Licenza.objects.first()
    if ultima is None:
        return _da_istanza() or Stato(False, "Nessuna licenza caricata.")
    return leggi(ultima.testo)


def _da_istanza():
    """Senza una licenza propria dell'assistente vale quella dell'istanza, se comprende il modulo."""
    istanza = licenza_istanza.attuale()
    if not istanza.valida or "ai" not in istanza.moduli:
        return None
    return Stato(not istanza.scaduta, f"La licenza è scaduta il {istanza.scadenza:%d/%m/%Y}." if istanza.scaduta else "",
                 cliente=istanza.cliente, scadenza=istanza.scadenza, utenti=istanza.utenti,
                 funzioni=istanza.funzioni.get("ai"))
