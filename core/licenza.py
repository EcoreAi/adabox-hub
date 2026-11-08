"""Licenza dell'istanza: quali moduli ha comprato questo cliente, per quanti utenti, fino a quando. È un JSON firmato
Ed25519 con le chiavi fidate del kernel (le stesse dei pacchetti) e arriva dal portale o da un file.

{"licenza": {"prodotto": "adabox-hub", "cliente": ..., "istanza": ..., "piano": ..., "moduli": ["crm", ...],
             "utenti": 25, "emessa": "<ISO>", "scadenza": "AAAA-MM-GG", "grazia_giorni": 30}, "firma": "<base64>"}

Vale solo con LICENZA_OBBLIGATORIA: senza licenza valida i moduli restano spenti; dopo la scadenza, finita la grazia,
l'istanza è in sola lettura. È un deterrente, non un muro: chi ha accesso root al server può togliere anche il
controllo. La protezione vera è che il codice dei moduli non comprati su quel server non arriva proprio."""
import datetime
import json
from dataclasses import dataclass, field
from functools import lru_cache

from django.conf import settings
from django.utils import timezone

from .registry import pacchetti

PRODOTTO = "adabox-hub"
GRAZIA_PREDEFINITA = 30


@dataclass
class Stato:
    valida: bool                                         # firma buona e dati leggibili (anche se scaduta)
    motivo: str = ""
    cliente: str = ""
    istanza: str = ""
    piano: str = ""
    moduli: frozenset = field(default_factory=frozenset)
    utenti: int = 0
    emessa: str = ""
    scadenza: datetime.date | None = None
    grazia_giorni: int = GRAZIA_PREDEFINITA
    suite: tuple = ()                                    # ({slug, nome, moduli: frozenset, utenti}, ...) comprate dall'istanza
    comuni: frozenset = field(default_factory=frozenset)  # le app del piano base: di tutti i dipartimenti

    @property
    def scaduta(self):
        return bool(self.scadenza and self.scadenza < timezone.localdate())

    @property
    def fine_grazia(self):
        return self.scadenza + datetime.timedelta(days=self.grazia_giorni) if self.scadenza else None

    @property
    def in_grazia(self):
        return self.scaduta and timezone.localdate() <= self.fine_grazia

    @property
    def bloccata(self):
        return not self.valida or (self.scaduta and not self.in_grazia)


def obbligatoria():
    return settings.LICENZA_OBBLIGATORIA


def firma(dati, privata):
    """Il file di licenza (dict) per i dati indicati, firmato con la chiave privata di ICHNOBYTE."""
    contenuto = {"prodotto": PRODOTTO, **dati}
    return {"licenza": contenuto, "firma": pacchetti.firma(pacchetti.serializza(contenuto), privata).decode()}


@lru_cache(maxsize=4)
def _leggi(testo, chiavi):
    try:
        dati = json.loads(testo)
        contenuto, segno = dati["licenza"], dati["firma"]
    except (ValueError, KeyError, TypeError):
        return Stato(False, "Il file non è una licenza leggibile.")
    if pacchetti.verifica(pacchetti.serializza(contenuto), segno, list(chiavi)) is None:
        return Stato(False, "Firma non valida o di una chiave non fidata.")
    if contenuto.get("prodotto") != PRODOTTO:
        return Stato(False, "La licenza è di un altro prodotto.")
    try:
        scadenza = datetime.date.fromisoformat(contenuto["scadenza"])
        return Stato(True, cliente=str(contenuto.get("cliente", "")), istanza=str(contenuto.get("istanza", "")),
                     piano=str(contenuto.get("piano", "")), moduli=frozenset(contenuto.get("moduli") or []),
                     utenti=int(contenuto.get("utenti") or 0), emessa=str(contenuto.get("emessa", "")), scadenza=scadenza,
                     grazia_giorni=int(contenuto.get("grazia_giorni", GRAZIA_PREDEFINITA)),
                     suite=_suite(contenuto.get("suite")), comuni=frozenset(contenuto.get("comuni") or []))
    except (KeyError, ValueError, TypeError):
        return Stato(False, "La licenza non ha dati validi.")


def _suite(voci):
    """Le suite della licenza, solo quelle scritte bene: una voce strana non invalida la licenza."""
    risultato = []
    for v in voci if isinstance(voci, list) else []:
        if isinstance(v, dict) and isinstance(v.get("slug"), str) and v["slug"]:
            risultato.append({"slug": v["slug"], "nome": str(v.get("nome") or v["slug"]),
                              "moduli": frozenset(m for m in v.get("moduli") or [] if isinstance(m, str)),
                              "utenti": v["utenti"] if isinstance(v.get("utenti"), int) and v["utenti"] > 0 else 0})
    return tuple(risultato)


def leggi(testo):
    """Lo Stato di un file di licenza, senza salvarlo. La firma si verifica una volta per testo (è in ogni richiesta)."""
    return _leggi(testo, tuple(pacchetti.chiavi_fidate()))


def _riga():
    from django.db import DatabaseError

    from .models import LicenzaIstanza
    try:
        return LicenzaIstanza.objects.first()
    except DatabaseError:                                # tabella non ancora pronta, es. durante migrate
        return None


def attuale():
    riga = _riga()
    if riga is None or not riga.testo:
        return Stato(False, "Nessuna licenza caricata.")
    return leggi(riga.testo)


def salva(testo, catalogo=None):
    """Sostituisce la licenza dell'istanza. Una valida non lascia il posto a una emessa prima di lei, così una risposta
    vecchia non riporta indietro i moduli. Restituisce lo Stato; ValueError se la licenza non è accettabile."""
    from .models import LicenzaIstanza
    stato = leggi(testo)
    if not stato.valida:
        raise ValueError(stato.motivo)
    riga = _riga() or LicenzaIstanza()
    if riga.testo:
        prima = leggi(riga.testo)
        if prima.valida and stato.emessa and prima.emessa and stato.emessa < prima.emessa:
            raise ValueError("Questa licenza è più vecchia di quella presente.")
    riga.testo = testo
    if catalogo is not None:
        riga.catalogo = catalogo
    riga.save()
    from . import dipartimenti
    dipartimenti.allinea_alle_suite(stato)                 # ogni suite comprata ha il suo dipartimento
    return stato


def fuori_licenza():
    """Gli slug installati che la licenza non copre: spenti come se fossero disattivati. Vuoto se non è obbligatoria."""
    if not obbligatoria():
        return frozenset()
    stato = attuale()
    moduli = stato.moduli if stato.valida else frozenset()
    return frozenset(settings.ADDONS_ATTIVI) - moduli


def ammesso(slug):
    if not obbligatoria():
        return True
    stato = attuale()
    return stato.valida and slug in stato.moduli


def bloccata():
    """Istanza in sola lettura: licenza assente, non valida o scaduta oltre la grazia."""
    return obbligatoria() and attuale().bloccata


def utenti_attivi():
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(is_active=True).count()


def posti_finiti():
    """True se la licenza ha un tetto di utenti ed è già raggiunto."""
    if not obbligatoria():
        return False
    stato = attuale()
    return bool(stato.utenti) and utenti_attivi() >= stato.utenti


def avviso():
    """Il testo della fascia per gli amministratori, se c'è qualcosa da dire."""
    if not obbligatoria():
        return ""
    stato = attuale()
    if not stato.valida:
        return f"{stato.motivo} I moduli sono spenti e l'istanza è in sola lettura."
    if stato.in_grazia:
        return f"La licenza è scaduta il {stato.scadenza:%d/%m/%Y}: dal {stato.fine_grazia:%d/%m/%Y} l'istanza passa in sola lettura."
    if stato.bloccata:
        return f"La licenza è scaduta il {stato.scadenza:%d/%m/%Y}: l'istanza è in sola lettura. Contatta ICHNOBYTE per rinnovarla."
    if stato.scadenza and (stato.scadenza - timezone.localdate()).days <= 30:
        return f"La licenza scade il {stato.scadenza:%d/%m/%Y}."
    if stato.suite:
        from . import dipartimenti
        return dipartimenti.avviso_posti()
    return ""
