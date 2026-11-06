"""Validazione dei dati fiscali italiani: partita IVA, codice fiscale, codice destinatario SDI."""
import re

from django.core.exceptions import ValidationError
from stdnum.eu import vat as vat_ue

CF_PERSONA_RE = re.compile(r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$")
SDI_RE = re.compile(r"^[A-Z0-9]{6,7}$")
ESTERA_RE = re.compile(r"^[A-Z0-9]{2,28}$")
UE = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV",
      "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI"}
DISPARI = dict(zip("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                   [1, 0, 5, 7, 9, 13, 15, 17, 19, 21] + [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3,
                                                          6, 8, 12, 14, 16, 10, 22, 25, 24, 23]))
PARI = {**{str(i): i for i in range(10)}, **{chr(65 + i): i for i in range(26)}}


def cifra_controllo_piva(prime10):
    totale = 0
    for i, c in enumerate(prime10):
        n = int(c)
        if i % 2 == 1:
            n *= 2
            n = n - 9 if n > 9 else n
        totale += n
    return str((10 - totale % 10) % 10)


def partita_iva_valida(valore):
    return bool(re.fullmatch(r"\d{11}", valore)) and cifra_controllo_piva(valore[:10]) == valore[10]


def carattere_controllo_cf(prime15):
    totale = sum(DISPARI[c] if i % 2 == 0 else PARI[c] for i, c in enumerate(prime15))
    return chr(65 + totale % 26)


def codice_fiscale_valido(valore):
    """16 caratteri con il carattere di controllo (persone) o 11 cifre come una partita IVA (società)."""
    if re.fullmatch(r"\d{11}", valore):
        return partita_iva_valida(valore)
    return bool(CF_PERSONA_RE.match(valore)) and carattere_controllo_cf(valore[:15]) == valore[15]


def valida_partita_iva(valore):
    if valore and not partita_iva_valida(valore):
        raise ValidationError("Partita IVA non valida (11 cifre con la cifra di controllo).")


def prefisso_iva(nazione):
    """Il prefisso IVA della Grecia è EL, non il suo codice ISO."""
    return "EL" if nazione == "GR" else nazione


def normalizza_partita_iva(valore, nazione):
    """Senza spazi e senza il prefisso del paese: il paese ha il suo campo."""
    pulito = re.sub(r"[\s.\-]", "", valore or "").upper()
    prefisso = prefisso_iva(nazione)
    return pulito[len(prefisso):] if pulito.startswith(prefisso) and len(pulito) > len(prefisso) else pulito


def errore_partita_iva(valore, nazione):
    """Il messaggio se la partita IVA non è valida per il paese, altrimenti None."""
    if not valore:
        return None
    if nazione == "IT":
        return None if partita_iva_valida(valore) else "Partita IVA non valida (11 cifre con la cifra di controllo)."
    if nazione in UE:
        return None if vat_ue.is_valid(prefisso_iva(nazione) + valore) else f"Partita IVA non valida per il paese {nazione}."
    return None if ESTERA_RE.match(valore) else "Identificativo fiscale estero non valido (lettere e cifre, al massimo 28)."


def valida_codice_fiscale(valore):
    if valore and not codice_fiscale_valido(valore.upper()):
        raise ValidationError("Codice fiscale non valido.")


def valida_sdi(valore):
    if valore and not SDI_RE.match(valore.upper()):
        raise ValidationError("Il codice destinatario ha 7 caratteri (6 per la Pubblica Amministrazione), lettere e cifre.")
