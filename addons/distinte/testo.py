"""Testi per i file della banca: solo i caratteri ammessi, alla lunghezza giusta."""
import re
import unicodedata

NON_SEPA = re.compile(r"[^A-Za-z0-9/\-?:().,'+ ]")


def ascii_(testo):
    return unicodedata.normalize("NFKD", str(testo or "")).encode("ascii", "ignore").decode()


def sepa(testo, lunghezza=140):
    """Il set di caratteri latino ridotto delle regole SEPA: niente accenti, &, @, _ ..."""
    pulito = re.sub(r"\s+", " ", NON_SEPA.sub(" ", ascii_(testo))).strip()
    return pulito[:lunghezza].strip() or "-"


def fisso(testo, lunghezza, numerico=False):
    """Campo a lunghezza fissa dei tracciati CBI: maiuscolo, a sinistra con spazi; i numeri a destra con zeri."""
    if numerico:
        cifre = re.sub(r"\D", "", str(testo or ""))[-lunghezza:]
        return cifre.rjust(lunghezza, "0")
    pulito = re.sub(r"[^A-Z0-9 .,'/\-&()]", " ", ascii_(testo).upper())
    return pulito[:lunghezza].ljust(lunghezza)


def _numeri(testo):
    return "".join(str(int(c, 36)) for c in testo)


def id_creditore_valido(valore):
    """Identificativo del creditore SEPA: paese, 2 cifre di controllo, codice attività (3, non conta), codice nazionale.
    Le cifre di controllo sono il mod 97 del codice nazionale seguito dal paese e da 00, come per l'IBAN."""
    valore = (valore or "").replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{3}[A-Z0-9]{1,28}", valore):
        return False
    nazionale = valore[7:]
    return 98 - int(_numeri(nazionale + valore[:2] + "00")) % 97 == int(valore[2:4])


def calcola_id_creditore(nazionale, paese="IT", attivita="ZZZ"):
    controllo = 98 - int(_numeri(nazionale.upper() + paese + "00")) % 97
    return f"{paese}{controllo:02d}{attivita}{nazionale.upper()}"
