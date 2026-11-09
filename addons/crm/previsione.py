"""Previsione delle vendite per mese: vinto nel mese più pipeline aperta ponderata (valore × probabilità) con
chiusura prevista nel mese; le trattative scadute contano nel mese corrente. Una rettifica manuale sostituisce la
previsione calcolata del mese."""
import datetime
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum

from .models import Opportunita, RettificaPrevisione


def primo(giorno):
    return giorno.replace(day=1)


def piu_mesi(giorno, n):
    anno, mese = divmod(giorno.year * 12 + giorno.month - 1 + n, 12)
    return datetime.date(anno, mese + 1, 1)


def previsione(azienda, utente=None, mesi=6, oggi=None):
    oggi = oggi or datetime.date.today()
    inizio = primo(oggi)
    tutte = Opportunita.objects.filter(azienda=azienda)
    if utente is not None:
        tutte = tutte.filter(commerciale=utente)
    ponderato = ExpressionWrapper(F("valore_atteso") * F("probabilita") / 100, output_field=DecimalField(max_digits=14, decimal_places=2))
    rettifiche = {r.mese: r for r in RettificaPrevisione.objects.filter(azienda=azienda, utente=utente, mese__gte=inizio)}
    righe = []
    for n in range(mesi):
        dal, al = piu_mesi(inizio, n), piu_mesi(inizio, n + 1) - datetime.timedelta(days=1)
        aperte = tutte.filter(stato=Opportunita.APERTA)
        aperte = aperte.filter(chiusura_prevista__lte=al) if n == 0 else aperte.filter(chiusura_prevista__range=(dal, al))
        if n == 0:                                   # le aperte senza data o già scadute contano nel mese corrente
            aperte = aperte | tutte.filter(stato=Opportunita.APERTA, chiusura_prevista__isnull=True)
        somme = aperte.aggregate(pipeline=Sum("valore_atteso"), ponderato=Sum(ponderato))
        vinto = tutte.filter(stato=Opportunita.VINTA, chiusa_il__range=(dal, al)).aggregate(s=Sum("valore_atteso"))["s"] or Decimal(0)
        calcolata = vinto + (somme["ponderato"] or Decimal(0))
        rettifica = rettifiche.get(dal)
        righe.append({"mese": dal, "vinto": vinto, "pipeline": somme["pipeline"] or Decimal(0), "ponderato": somme["ponderato"] or Decimal(0),
                      "calcolata": calcolata, "rettifica": rettifica,
                      "previsione": rettifica.importo if rettifica else calcolata, "aperte": aperte.distinct().count()})
    totale = {k: sum((r[k] for r in righe), Decimal(0)) for k in ("vinto", "pipeline", "ponderato", "calcolata", "previsione")}
    return righe, totale


def rettifica(azienda, mese, importo, utente=None, nota="", autore=None):
    """Imposta (o, con importo None, toglie) la rettifica del mese."""
    mese = primo(mese)
    if importo is None:
        RettificaPrevisione.objects.filter(azienda=azienda, mese=mese, utente=utente).delete()
        return None
    r, _ = RettificaPrevisione.objects.update_or_create(azienda=azienda, mese=mese, utente=utente,
                                                        defaults={"importo": importo, "nota": nota[:200], "autore": autore})
    return r
