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


def maturate(dipendente, anno, oggi=None):
    """Ratei mensili: la parte di spettanza maturata fino al mese in corso (un dodicesimo per mese lavorato)."""
    import datetime
    oggi = oggi or datetime.date.today()
    if anno < oggi.year:
        mesi = 12
    elif anno > oggi.year:
        return {"ferie": Decimal(0), "permessi": Decimal(0)}
    else:
        inizio = dipendente.data_assunzione.month if dipendente.data_assunzione.year == anno else 1
        mesi = max(oggi.month - inizio + 1, 0)
        if dipendente.data_cessazione and dipendente.data_cessazione.year == anno:
            mesi = min(mesi, dipendente.data_cessazione.month - inizio + 1)
    if dipendente.data_assunzione.year > anno:
        mesi = 0
    return {"ferie": _q(dipendente.giorni_ferie_annui * mesi / 12), "permessi": _q(dipendente.ore_permesso_annue * mesi / 12)}


def riporto(dipendente, anno, profondita=5):
    """Il residuo dell'anno prima che passa a questo (anche negativo), dall'anno scelto nelle impostazioni
    (personale.riporto_dal: prima di allora le assenze potrebbero non essere registrate qui) e non prima dell'assunzione."""
    from core import parametri
    try:
        dal = int(parametri.leggi("personale.riporto_dal", dipendente.azienda) or 0)
    except KeyError:
        dal = 0
    if not dal or profondita <= 0 or anno - 1 < max(dal, dipendente.data_assunzione.year):
        return {"ferie": Decimal(0), "permessi": Decimal(0)}
    prima = saldo(dipendente, anno - 1, _profondita=profondita - 1, solo_godute=True)
    return {k: prima[k]["residue"] for k in ("ferie", "permessi")}


def saldo(dipendente, anno, _profondita=5, solo_godute=False):
    """{"ferie": {...}, "permessi": {...}} con spettanti, maturate (ratei a oggi), riporto dall'anno prima, godute,
    richieste (da approvare) e residue (riporto + spettanti − godute − richieste)."""
    frazione = frazione_lavorata(dipendente, anno)
    da_prima = riporto(dipendente, anno, _profondita)
    ratei = maturate(dipendente, anno)
    spettanze = {"ferie": dipendente.giorni_ferie_annui * frazione, "permessi": dipendente.ore_permesso_annue * frazione}
    assenze = (dipendente.assenze.filter(dal__year=anno, tipo__saldo__in=["ferie", "permessi"])
               .exclude(stato__in=[Assenza.RIFIUTATA, Assenza.ANNULLATA]).select_related("tipo"))
    risultato = {}
    for chiave, spettanti in spettanze.items():
        godute = sum((_nel_saldo(a, chiave, dipendente) for a in assenze
                      if a.tipo.saldo == chiave and a.stato == Assenza.APPROVATA), Decimal(0))
        richieste = sum((_nel_saldo(a, chiave, dipendente) for a in assenze
                         if a.tipo.saldo == chiave and a.stato == Assenza.RICHIESTA), Decimal(0))
        if solo_godute:                                  # per il riporto contano solo quelle davvero godute
            richieste = Decimal(0)
        risultato[chiave] = {"unita": "giorni" if chiave == "ferie" else "ore", "spettanti": _q(spettanti),
                             "maturate": ratei[chiave], "riporto": _q(da_prima[chiave]),
                             "godute": _q(godute), "richieste": _q(richieste),
                             "residue": _q(da_prima[chiave] + spettanti - godute - richieste)}
    return risultato
