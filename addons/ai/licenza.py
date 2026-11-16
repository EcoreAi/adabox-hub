"""Licenza del modulo AI: JSON firmato Ed25519 con le chiavi fidate del kernel (le stesse dei pacchetti).

{"licenza": {"prodotto": "adabox-hub-ai", "cliente": ..., "emessa": "AAAA-MM-GG", "scadenza": "AAAA-MM-GG",
             "utenti": 25, "funzioni": ["ricerca_web", "memoria", ...]}, "firma": "<base64>"}

"funzioni" sono le chiavi del catalogo nel manifest (core.funzioni); senza, le comprende tutte. Le licenze emesse
prima del catalogo avevano ["chat", "strumenti", ...], di cui contava solo "chat": valgono come tutte. Senza una
licenza propria valgono le funzioni dell'assistente nella licenza dell'istanza.

La formula con cui l'assistente è venduto sta nella licenza: "formula" (propria, inclusa, consumo), "quota_utente" e
"quota_istanza", in dollari di costo dei modelli al mese ("0" o assente = senza limite). Nella licenza dell'istanza
stanno sotto la chiave "ai", che il kernel non legge: la firma copre comunque tutto il contenuto. Senza termini, o
con termini scritti male, vale «propria»: il cliente usa la sua chiave, come prima che le formule esistessero.
- propria: la chiave è del cliente, nessuna quota;
- inclusa: l'assistente è nel canone, fino alla quota mensile per utente e per istanza;
- consumo: si fattura l'utilizzo; la quota dell'istanza, se c'è, è il tetto massimo.
Le quote contano solo il costo sui provider «forniti con il piano» (Provider.gestito): vedi ai.limiti."""
import datetime
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from django.conf import settings
from django.utils import timezone

from core import licenza as licenza_istanza
from core.registry import pacchetti

from .models import Licenza

PRODOTTO = "adabox-hub-ai"
VECCHIO_FORMATO = {"chat", "strumenti"}                 # chiavi delle licenze emesse prima del catalogo
PROPRIA, INCLUSA, CONSUMO = "propria", "inclusa", "consumo"
FORMULE = {PROPRIA: "Chiave del cliente", INCLUSA: "Assistente incluso nel canone", CONSUMO: "Assistente a consumo"}


@dataclass
class Stato:
    valida: bool
    motivo: str = ""
    cliente: str = ""
    scadenza: datetime.date | None = None
    utenti: int = 0
    funzioni: frozenset | None = None                   # chiavi comprese; None = tutte
    sviluppo: bool = False
    formula: str = PROPRIA
    quota_utente: Decimal = Decimal(0)                  # $ al mese sui provider forniti con il piano; 0 = senza limite
    quota_istanza: Decimal = Decimal(0)

    @property
    def nome_formula(self):
        return FORMULE[self.formula]


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
                  utenti=int(contenuto.get("utenti") or 0), funzioni=_funzioni(contenuto.get("funzioni")),
                  **termini(contenuto))
    if scadenza < timezone.localdate():
        stato.valida, stato.motivo = False, f"La licenza è scaduta il {scadenza:%d/%m/%Y}."
    return stato


def _funzioni(lista):
    if not isinstance(lista, list) or VECCHIO_FORMATO & set(lista):
        return None
    return frozenset(f for f in lista if isinstance(f, str))


def _quota(valore):
    try:
        quota = Decimal(str(valore or 0))
    except InvalidOperation:
        return Decimal(0)
    return quota if quota.is_finite() and quota > 0 else Decimal(0)


def termini(dati):
    """{formula, quota_utente, quota_istanza} da un pezzo di licenza. Ciò che è scritto male non vale: una formula
    sconosciuta è «propria», una quota illeggibile è nessuna quota."""
    dati = dati if isinstance(dati, dict) else {}
    formula = dati.get("formula")
    return {"formula": formula if isinstance(formula, str) and formula in FORMULE else PROPRIA,
            "quota_utente": _quota(dati.get("quota_utente")), "quota_istanza": _quota(dati.get("quota_istanza"))}


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
    testo = _testo_istanza()
    istanza = licenza_istanza.leggi(testo) if testo else None
    if istanza is None or not istanza.valida or "ai" not in istanza.moduli:
        return None
    return Stato(not istanza.scaduta, f"La licenza è scaduta il {istanza.scadenza:%d/%m/%Y}." if istanza.scaduta else "",
                 cliente=istanza.cliente, scadenza=istanza.scadenza, utenti=istanza.utenti,
                 funzioni=istanza.funzioni.get("ai"), **termini(_termini_nel_testo(testo)))


def _testo_istanza():
    from django.db import DatabaseError

    from core.models import LicenzaIstanza
    try:
        riga = LicenzaIstanza.objects.first()
    except DatabaseError:                                # tabella non ancora pronta, es. durante migrate
        return ""
    return riga.testo if riga is not None else ""


@lru_cache(maxsize=4)
def _termini_nel_testo(testo):
    """La chiave "ai" di una licenza dell'istanza già verificata: il kernel la firma ma non la legge."""
    try:
        return json.loads(testo)["licenza"].get("ai")
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
