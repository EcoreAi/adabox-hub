"""Provvigioni dei commerciali: maturano alla conferma dell'ordine o, per i piani «all'incasso», in proporzione agli
incassi delle fatture dell'ordine; l'annullamento dell'ordine annulla quelle non ancora liquidate. L'estratto del
periodo somma le maturate e, se il commerciale ha raggiunto il suo obiettivo (CRM), aggiunge la maggiorazione."""
import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.apps import apps
from django.db import transaction
from django.db.models import Q, Sum

from .models import OrdineVendita, PianoProvvigioni, Provvigione

CENT = Decimal("0.01")


def piano_per(utente, azienda_id, giorno):
    if utente is None:
        return None
    validi = (PianoProvvigioni.objects.filter(azienda_id=azienda_id, attivo=True)
              .filter(Q(dal__isnull=True) | Q(dal__lte=giorno)).filter(Q(al__isnull=True) | Q(al__gte=giorno)))
    return validi.filter(utente=utente).first() or validi.filter(utente__isnull=True).first()


def calcola(ordine, piano):
    """(imponibile, provvigione) dell'ordine con le percentuali del piano, riga per riga."""
    regole = list(piano.regole.all())
    base = provvigione = Decimal(0)
    for r in ordine.righe.select_related("prodotto"):
        if getattr(r, "opzionale", False) and not getattr(r, "scelta", False):
            continue
        base += r.importo
        provvigione += r.importo * piano.percentuale_per(r.prodotto, regole) / 100
    return base, provvigione.quantize(CENT, ROUND_HALF_UP)


def da_conferma(sender, ordine, utente=None, **kwargs):
    piano = piano_per(ordine.commerciale, ordine.azienda_id, ordine.confermato_il or datetime.date.today())
    if piano is None or piano.maturazione != PianoProvvigioni.ORDINE or ordine.provvigioni.exclude(stato=Provvigione.ANNULLATA).exists():
        return None
    base, importo = calcola(ordine, piano)
    if not importo:
        return None
    Provvigione.objects.create(azienda_id=ordine.azienda_id, utente=ordine.commerciale, piano=piano, ordine=ordine,
                               data=ordine.confermato_il or datetime.date.today(), base=base, importo=importo,
                               descrizione=f"Ordine {ordine.numero_ordine or ordine.numero} · {ordine.cliente}")
    return None


def da_annullamento(sender, ordine, utente=None, **kwargs):
    n = ordine.provvigioni.filter(stato=Provvigione.MATURATA).update(stato=Provvigione.ANNULLATA)
    return f"Annullate {n} provvigioni." if n else None


def da_incasso(sender, instance, created, raw=False, **kwargs):
    """post_save dell'Incasso: matura la quota della provvigione pari alla quota incassata della fattura. Se l'incasso
    si corregge, la sua provvigione ancora da liquidare si ricalcola (o si annulla, se non resta niente)."""
    if raw:
        return
    fattura = instance.scadenza.fattura
    ordine = fattura.ordine
    if ordine is None:
        return
    piano = piano_per(ordine.commerciale, ordine.azienda_id, instance.data)
    if piano is None or piano.maturazione != PianoProvvigioni.INCASSO:
        return
    base = importo = Decimal(0)
    base_ordine, provv_ordine = calcola(ordine, piano)
    if instance.importo > 0 and fattura.totale > 0 and base_ordine:
        quota = min(Decimal(instance.importo) / fattura.totale, Decimal(1))
        aliquota_media = provv_ordine / base_ordine                 # la provvigione media dell'ordine sul venduto
        base = (fattura.imponibile * quota).quantize(CENT, ROUND_HALF_UP)
        importo = (base * aliquota_media).quantize(CENT, ROUND_HALF_UP)
    esistente = None if created else Provvigione.objects.filter(incasso_id=instance.pk).exclude(stato=Provvigione.ANNULLATA).first()
    if esistente is not None:
        if esistente.stato != Provvigione.MATURATA:                 # già liquidata: resta com'era
            return
        if importo:
            Provvigione.objects.filter(pk=esistente.pk).update(base=base, importo=importo, data=instance.data, piano=piano)
        else:
            Provvigione.objects.filter(pk=esistente.pk).update(stato=Provvigione.ANNULLATA)
    elif importo:
        Provvigione.objects.create(azienda_id=ordine.azienda_id, utente=ordine.commerciale, piano=piano, ordine=ordine,
                                   data=instance.data, base=base, importo=importo, incasso_id=instance.pk,
                                   descrizione=f"Incasso fattura {fattura.numero} · {fattura.cliente}")


def incasso_eliminato(sender, instance, **kwargs):
    Provvigione.objects.filter(incasso_id=instance.pk, stato=Provvigione.MATURATA).update(stato=Provvigione.ANNULLATA)


def _obiettivo(utente, azienda_id, dal, al):
    """(importo obiettivo, venduto confermato nel periodo) se c'è il CRM e un obiettivo del commerciale nel periodo."""
    if not apps.is_installed("crm"):
        return None, None
    from crm.models import ObiettivoVendita
    ob = ObiettivoVendita.objects.filter(azienda_id=azienda_id, utente=utente, dal__lte=al, al__gte=dal).order_by("-al").first()
    if ob is None:
        return None, None
    venduto = (OrdineVendita.objects.filter(azienda_id=azienda_id, commerciale=utente, stato=OrdineVendita.CONFERMATO,
                                            confermato_il__range=(ob.dal, ob.al)).aggregate(s=Sum("imponibile"))["s"] or Decimal(0))
    return ob, venduto


def estratto(utente, azienda_id, dal, al):
    righe = list(Provvigione.objects.filter(azienda_id=azienda_id, utente=utente, data__range=(dal, al))
                 .exclude(stato=Provvigione.ANNULLATA).select_related("ordine", "piano").order_by("data", "pk"))
    base = sum((r.base for r in righe), Decimal(0))
    totale = sum((r.importo for r in righe), Decimal(0))
    ob, venduto = _obiettivo(utente, azienda_id, dal, al)
    piano = piano_per(utente, azienda_id, al)
    raggiunto = ob is not None and venduto >= ob.importo
    bonus = (base * piano.maggiorazione / 100).quantize(CENT, ROUND_HALF_UP) if raggiunto and piano and piano.maggiorazione else Decimal(0)
    return {"righe": righe, "base": base, "totale": totale, "obiettivo": ob, "venduto": venduto, "raggiunto": raggiunto,
            "percentuale_obiettivo": round(venduto / ob.importo * 100) if ob and ob.importo else None,
            "maggiorazione": bonus, "da_pagare": totale + bonus,
            "da_liquidare": sum((r.importo for r in righe if r.stato == Provvigione.MATURATA), Decimal(0))}


@transaction.atomic
def liquida(utente, azienda_id, dal, al, giorno=None):
    return Provvigione.objects.filter(azienda_id=azienda_id, utente=utente, data__range=(dal, al), stato=Provvigione.MATURATA
                                      ).update(stato=Provvigione.LIQUIDATA, liquidata_il=giorno or datetime.date.today())
