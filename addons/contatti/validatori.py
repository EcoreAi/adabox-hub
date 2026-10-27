"""Validazione dei dati fiscali italiani: partita IVA, codice fiscale, codice destinatario SDI."""
import re

from django.core.exceptions import ValidationError

CF_PERSONA_RE = re.compile(r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$")
SDI_RE = re.compile(r"^[A-Z0-9]{7}$")
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


def valida_codice_fiscale(valore):
    if valore and not codice_fiscale_valido(valore.upper()):
        raise ValidationError("Codice fiscale non valido.")


def valida_sdi(valore):
    if valore and not SDI_RE.match(valore.upper()):
        raise ValidationError("Il codice destinatario SDI ha 7 caratteri (lettere maiuscole e cifre).")
