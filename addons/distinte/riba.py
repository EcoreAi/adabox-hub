"""Ricevute bancarie nel tracciato CBI «RIBA»: record da 120 caratteri, testa IB, sette record per ricevuta
(14, 20, 30, 40, 50, 51, 70) e coda EF. Importi in centesimi, date GGMMAA."""
from django.core.exceptions import ValidationError
from django.utils import timezone

from .testo import fisso

LUNGHEZZA = 120


def _riga(*campi):
    riga = "".join(campi)
    if len(riga) != LUNGHEZZA:
        raise ValueError(f"record di {len(riga)} caratteri invece di {LUNGHEZZA}: {riga!r}")
    return riga


def _data(d):
    return d.strftime("%d%m%y")


def _centesimi(importo, cifre):
    return fisso(int(round(importo * 100)), cifre, numerico=True)


def coordinate_azienda(conto):
    iban = conto.iban
    if not iban.startswith("IT") or len(iban) != 27:
        raise ValidationError("Le RiBa si presentano da un conto italiano: l'IBAN del conto deve iniziare con IT.")
    return iban[5:10], iban[10:15], iban[15:27]


def genera(distinta, voci, codice_sia, coordinate_cliente):
    """coordinate_cliente(voce) -> (abi, cab, banca, contatto). Restituisce il testo del file (righe separate da CRLF)."""
    abi, cab, conto = coordinate_azienda(distinta.conto)
    azienda = distinta.azienda
    oggi = _data(timezone.localdate())
    supporto = fisso(distinta.identificativo, 20)
    cf_azienda = (azienda.codice_fiscale or azienda.partita_iva or "").upper()
    righe = [_riga(" IB", fisso(codice_sia, 5), fisso(abi, 5, True), oggi, supporto, " " * 6, " " * 59, " " * 7, " " * 2, "E",
                   " " * 6)]
    for n, v in enumerate(voci, start=1):
        prog = fisso(n, 7, numerico=True)
        abi_c, cab_c, banca, contatto = coordinate_cliente(v)
        codice_cliente = (contatto.partita_iva or contatto.codice_fiscale or "").upper()
        righe.append(_riga(" 14", prog, " " * 12, _data(v.data), "30000", _centesimi(v.importo, 13), "-", fisso(abi, 5, True),
                           fisso(cab, 5, True), fisso(conto, 12), fisso(abi_c, 5, True), fisso(cab_c, 5, True), " " * 12,
                           fisso(codice_sia, 5), "4", fisso(codice_cliente, 16), " " * 6, "E"))
        righe.append(_riga(" 20", prog, fisso(azienda.nome, 24), fisso(azienda.indirizzo, 24),
                           fisso(f"{azienda.cap} {azienda.citta}".strip(), 24), fisso(cf_azienda, 24), " " * 14))
        righe.append(_riga(" 30", prog, fisso(contatto.nome, 30), fisso(contatto.nome[30:], 30), fisso(codice_cliente, 16),
                           " " * 34))
        luogo = f"{contatto.citta} {contatto.provincia}".strip()
        righe.append(_riga(" 40", prog, fisso(contatto.indirizzo, 30), fisso(contatto.cap, 5, True) if contatto.cap else " " * 5,
                           fisso(luogo, 25), fisso(banca, 50)))
        righe.append(_riga(" 50", prog, fisso(v.causale, 40), fisso(v.causale[40:], 40), " " * 10, fisso(cf_azienda, 16), " " * 4))
        righe.append(_riga(" 51", prog, fisso(n, 10, numerico=True), fisso(azienda.nome, 20), " " * 15, " " * 10, " " * 6,
                           " " * 49))
        righe.append(_riga(" 70", prog, " " * 78, " " * 12, " " * 20))
    totale = sum(v.importo for v in voci)
    righe.append(_riga(" EF", fisso(codice_sia, 5), fisso(abi, 5, True), oggi, supporto, " " * 6, fisso(len(voci), 7, True),
                       _centesimi(totale, 15), fisso(0, 15, True), fisso(len(righe) + 1, 7, True), " " * 24, "E", " " * 6))
    return "\r\n".join(righe) + "\r\n"
