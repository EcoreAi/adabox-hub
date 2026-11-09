"""Piano delle rate di un finanziamento e operazioni: genera (o rigenera le rate non pagate), paga, annulla il
pagamento, estinzione anticipata. Ammortamento francese (rata costante) o italiano (quota capitale costante),
con eventuale preammortamento di soli interessi; l'ultima rata chiude il debito al centesimo."""
import calendar
import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction

from core import chatter

from .models import Finanziamento, RataFinanziamento

CENT = Decimal("0.01")


def piu_mesi(giorno, mesi):
    anno, mese = divmod(giorno.year * 12 + giorno.month - 1 + mesi, 12)
    return datetime.date(anno, mese + 1, min(giorno.day, calendar.monthrange(anno, mese + 1)[1]))


def _c(valore):
    return Decimal(valore).quantize(CENT, ROUND_HALF_UP)


def calcola(capitale, tasso, numero_rate, periodicita, ammortamento, preammortamento=0, dal_numero=1):
    """[(numero, quota capitale, quota interessi, debito residuo dopo)] dalle rata `dal_numero` con `capitale` residuo."""
    r = Decimal(tasso) / 100 * periodicita / 12
    residuo, righe = Decimal(capitale), []
    rata_fissa = None
    for n in range(dal_numero, numero_rate + 1):
        interessi = _c(residuo * r)
        if n <= preammortamento:
            quota = Decimal(0)
        else:
            rimanenti = numero_rate - n + 1
            if n == numero_rate:
                quota = residuo
            elif ammortamento == Finanziamento.ITALIANO:
                quota = _c(residuo / rimanenti)
            else:
                if rata_fissa is None:                  # la rata al centesimo; la quota capitale è rata meno interessi
                    rata_fissa = _c(residuo / rimanenti if r == 0 else residuo * r / (1 - (1 + r) ** -rimanenti))
                quota = min(residuo, rata_fissa - interessi)
        residuo -= quota
        righe.append((n, quota, interessi, residuo))
    return righe


@transaction.atomic
def genera(f):
    """Rigenera le rate non pagate dal debito residuo: quelle già pagate restano come sono. Restituisce quante."""
    f = Finanziamento.objects.select_for_update().get(pk=f.pk)
    if f.stato == Finanziamento.ESTINTO:
        raise ValidationError("Il finanziamento è estinto.")
    pagate = list(f.rate.filter(pagata=True).order_by("numero"))
    f.rate.filter(pagata=False).delete()
    dal = (pagate[-1].numero + 1) if pagate else 1
    if dal > f.numero_rate:
        return 0
    residuo = f.capitale - sum((p.quota_capitale for p in pagate), Decimal(0))
    nuove = [RataFinanziamento(azienda_id=f.azienda_id, finanziamento=f, numero=n,
                               data=piu_mesi(f.prima_rata, (n - 1) * f.periodicita),
                               quota_capitale=q, quota_interessi=i, spese=f.spese_rata, importo=q + i + f.spese_rata,
                               debito_residuo=d)
             for n, q, i, d in calcola(residuo, f.tasso, f.numero_rate, f.periodicita, f.ammortamento, f.preammortamento, dal)]
    RataFinanziamento.objects.bulk_create(nuove)
    return len(nuove)


def _chiudi_se_finito(f):
    if not f.rate.filter(pagata=False).exists() and f.rate.exists():
        Finanziamento.objects.filter(pk=f.pk).update(stato=Finanziamento.ESTINTO)
        chatter.scrivi(f, None, "Tutte le rate sono pagate: finanziamento estinto.", tipo="sistema")


@transaction.atomic
def paga(rata, data, utente=None, movimento=None):
    rata = RataFinanziamento.objects.select_for_update().select_related("finanziamento").get(pk=rata.pk)
    if rata.pagata:
        raise ValidationError("La rata è già pagata.")
    if movimento is not None:
        from banca import abbina
        abbina.abbina_documento(movimento, rata, rata.importo, utente)
        data = data or movimento.data
    rata.pagata, rata.pagata_il = True, data
    rata.save(update_fields=["pagata", "pagata_il"])
    chatter.scrivi(rata.finanziamento, utente, f"Pagata la rata {rata.numero} del {rata.data:%d/%m/%Y}: {rata.importo} €"
                   + (f", abbinata al movimento del {movimento.data:%d/%m/%Y}." if movimento else "."), tipo="sistema")
    _chiudi_se_finito(rata.finanziamento)
    return rata


@transaction.atomic
def annulla_pagamento(rata, utente=None):
    rata = RataFinanziamento.objects.select_for_update().select_related("finanziamento").get(pk=rata.pk)
    if not rata.pagata:
        return rata
    if apps.is_installed("banca"):
        from banca import abbina
        for a in abbina.abbinamenti_di(rata):
            abbina.annulla(a)
    rata.pagata, rata.pagata_il = False, None
    rata.save(update_fields=["pagata", "pagata_il"])
    f = rata.finanziamento
    if f.stato == Finanziamento.ESTINTO:
        Finanziamento.objects.filter(pk=f.pk).update(stato=Finanziamento.ATTIVO)
    chatter.scrivi(f, utente, f"Annullato il pagamento della rata {rata.numero}.", tipo="sistema")
    return rata


@transaction.atomic
def estingui(f, data, penale=Decimal(0), utente=None):
    """Estinzione anticipata: le rate non pagate si tolgono e ne resta una, al giorno `data`, con il debito residuo,
    gli interessi maturati dall'ultima scadenza e la penale. Si segna pagata con «Paga» come le altre."""
    f = Finanziamento.objects.select_for_update().get(pk=f.pk)
    if f.stato == Finanziamento.ESTINTO:
        raise ValidationError("Il finanziamento è già estinto.")
    pagate = list(f.rate.filter(pagata=True).order_by("numero"))
    residuo = f.capitale - sum((p.quota_capitale for p in pagate), Decimal(0))
    dall = pagate[-1].data if pagate else f.erogato_il
    giorni = max((data - dall).days, 0)
    interessi = _c(residuo * Decimal(f.tasso) / 100 * giorni / 365)
    penale = _c(penale or 0)
    f.rate.filter(pagata=False).delete()
    numero = (pagate[-1].numero + 1) if pagate else 1
    rata = RataFinanziamento.objects.create(azienda_id=f.azienda_id, finanziamento=f, numero=numero, data=data,
                                            quota_capitale=residuo, quota_interessi=interessi, spese=penale,
                                            importo=residuo + interessi + penale, debito_residuo=0)
    chatter.scrivi(f, utente, f"Estinzione anticipata al {data:%d/%m/%Y}: capitale {residuo} €, interessi {interessi} €"
                   + (f", penale {penale} €" if penale else "") + ".", tipo="sistema")
    return rata


def riepilogo(f, oggi=None):
    rate = list(f.rate.all())
    oggi = oggi or datetime.date.today()
    da_pagare = [r for r in rate if not r.pagata]
    return {"rate": rate, "pagate": len(rate) - len(da_pagare), "da_pagare": len(da_pagare),
            "residuo": f.debito_residuo(), "interessi_totali": sum((r.quota_interessi for r in rate), Decimal(0)),
            "interessi_da_pagare": sum((r.quota_interessi for r in da_pagare), Decimal(0)),
            "prossima": da_pagare[0] if da_pagare else None,
            "scadute": [r for r in da_pagare if r.data < oggi]}
