"""Saldo di ferie e permessi di un dipendente per anno (spettanze in proporzione al periodo lavorato)."""
import datetime
from decimal import ROUND_HALF_UP, Decimal

from .models import Assenza


def _q(valore):
    return Decimal(valore).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def frazione_lavorata(dipendente, anno):
    inizio, fine = datetime.date(anno, 1, 1), datetime.date(anno, 12, 31)
    dal = max(inizio, dipendente.data_assunzione or inizio)
    al = min(fine, dipendente.data_cessazione or fine)
    if al < dal:
        return Decimal(0)
    return Decimal((al - dal).days + 1) / Decimal((fine - inizio).days + 1)


def _nel_saldo(assenza, saldo, dipendente):
    """Quanto pesa l'assenza sul saldo (giorni per le ferie, ore per i permessi)."""
    q = assenza.quantita
    if saldo == "ferie" and assenza.tipo.unita == "ore":
        return q / dipendente.ore_al_giorno
    if saldo == "permessi" and assenza.tipo.unita == "giorni":
        return q * dipendente.ore_al_giorno
    return q


def saldo(dipendente, anno):
    """{"ferie": {...}, "permessi": {...}} con spettanti, godute, richieste (da approvare) e residue."""
    frazione = frazione_lavorata(dipendente, anno)
    spettanze = {"ferie": dipendente.giorni_ferie_annui * frazione, "permessi": dipendente.ore_permesso_annue * frazione}
    assenze = (dipendente.assenze.filter(dal__year=anno, tipo__saldo__in=["ferie", "permessi"])
               .exclude(stato__in=[Assenza.RIFIUTATA, Assenza.ANNULLATA]).select_related("tipo"))
    risultato = {}
    for chiave, spettanti in spettanze.items():
        godute = sum((_nel_saldo(a, chiave, dipendente) for a in assenze
                      if a.tipo.saldo == chiave and a.stato == Assenza.APPROVATA), Decimal(0))
        richieste = sum((_nel_saldo(a, chiave, dipendente) for a in assenze
                         if a.tipo.saldo == chiave and a.stato == Assenza.RICHIESTA), Decimal(0))
        risultato[chiave] = {"unita": "giorni" if chiave == "ferie" else "ore", "spettanti": _q(spettanti),
                             "godute": _q(godute), "richieste": _q(richieste),
                             "residue": _q(spettanti - godute - richieste)}
    return risultato
