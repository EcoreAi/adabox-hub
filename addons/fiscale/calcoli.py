"""Importi dei documenti: arrotondamenti al centesimo, riepilogo IVA per aliquota, scadenze delle rate."""
import calendar
from collections import OrderedDict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

CENTESIMO = Decimal("0.01")


def arrotonda(valore):
    return Decimal(valore or 0).quantize(CENTESIMO, rounding=ROUND_HALF_UP)


def importo_riga(quantita, prezzo, sconto=0):
    """Imponibile di una riga: quantità × prezzo, meno lo sconto percentuale, arrotondato al centesimo."""
    lordo = Decimal(quantita or 0) * Decimal(prezzo or 0)
    return arrotonda(lordo * (Decimal(100) - Decimal(sconto or 0)) / Decimal(100))


def riepilogo_iva(righe):
    """righe: [(imponibile, aliquota)]. Per aliquota: imponibile sommato e imposta calcolata sul totale
    dell'aliquota (come il riepilogo della fattura elettronica). Restituisce [{aliquota, imponibile, imposta}]."""
    gruppi = OrderedDict()
    for imponibile, aliquota in righe:
        if aliquota is None:
            continue
        gruppi.setdefault(aliquota.pk, {"aliquota": aliquota, "imponibile": Decimal(0)})
        gruppi[aliquota.pk]["imponibile"] += Decimal(imponibile)
    risultato = []
    for g in gruppi.values():
        g["imponibile"] = arrotonda(g["imponibile"])
        g["imposta"] = arrotonda(g["imponibile"] * g["aliquota"].percentuale / Decimal(100))
        risultato.append(g)
    return risultato


def totali(righe):
    """(imponibile, imposta, totale) dalle righe [(imponibile, aliquota)]."""
    riepilogo = riepilogo_iva(righe)
    imponibile = sum((g["imponibile"] for g in riepilogo), Decimal(0))
    imposta = sum((g["imposta"] for g in riepilogo), Decimal(0))
    return arrotonda(imponibile), arrotonda(imposta), arrotonda(imponibile + imposta)


def _fine_mese(data):
    return data.replace(day=calendar.monthrange(data.year, data.month)[1])


def scadenze(termine, data_documento, importo):
    """[(data, importo)] delle rate; l'ultima rata prende i centesimi che avanzano."""
    importo = arrotonda(importo)
    rate = termine.rate if termine else [{"giorni": 0, "percentuale": 100}]
    risultato, assegnato = [], Decimal(0)
    for i, r in enumerate(rate):
        data = data_documento + timedelta(days=r["giorni"])
        if r.get("fine_mese"):
            data = _fine_mese(data)
        quota = importo - assegnato if i == len(rate) - 1 else arrotonda(importo * Decimal(str(r["percentuale"])) / 100)
        assegnato += quota
        risultato.append((data, quota))
    return risultato
