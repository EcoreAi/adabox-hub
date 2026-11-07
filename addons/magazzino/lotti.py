"""Lotti e seriali sulle righe di ricevimenti e consegne: lettura del campo «lotti», controlli, scelta automatica."""
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from .models import Lotto, Movimento, Tracciamento, tracciamento


def leggi(testo, quantita, prodotto):
    """[(codice, quantità)] dal testo della riga. Per i seriali una unità ciascuno, tante quante la riga."""
    tipo, quantita = tracciamento(prodotto), Decimal(quantita)
    voci = [v.strip() for v in re.split(r"[\n,;]+", testo or "") if v.strip()]
    if not voci:
        return []
    coppie = []
    for v in voci:
        codice, _, numero = v.partition(":")
        codice = codice.strip()
        if not codice:
            raise ValidationError(f"{prodotto}: manca il codice in «{v}».")
        if numero.strip():
            try:
                q = Decimal(numero.strip().replace(",", "."))
            except InvalidOperation:
                raise ValidationError(f"{prodotto}: quantità non valida in «{v}».") from None
        else:
            q = Decimal(1) if tipo == Tracciamento.SERIALE else (quantita if len(voci) == 1 else None)
            if q is None:
                raise ValidationError(f"{prodotto}: con più lotti indica la quantità di ciascuno (es. L24A:5, L24B:3).")
        if q <= 0 or (tipo == Tracciamento.SERIALE and q != 1):
            raise ValidationError(f"{prodotto}: quantità non valida per {codice}.")
        coppie.append((codice, q))
    codici = [c for c, _ in coppie]
    if len(set(codici)) != len(codici):
        raise ValidationError(f"{prodotto}: un codice compare due volte.")
    if sum(q for _, q in coppie) != quantita:
        raise ValidationError(f"{prodotto}: i lotti sommano a {sum(q for _, q in coppie):g}, la riga dice {quantita:g}.")
    return coppie


def per_entrata(riga, prodotto):
    """[(lotto o None, quantità)] per un carico. I lotti nuovi si creano; un seriale già in giacenza no."""
    if not tracciamento(prodotto):
        return [(None, Decimal(riga.quantita))]
    coppie = leggi(riga.lotti, riga.quantita, prodotto)
    if not coppie:
        raise ValidationError(f"{prodotto} si segue per lotto o seriale: scrivili sulla riga.")
    risultato = []
    for codice, q in coppie:
        lotto, _ = Lotto.objects.get_or_create(prodotto=prodotto, codice=codice, defaults={"azienda": prodotto.azienda})
        if lotto.seriale and saldo(lotto) > 0:
            raise ValidationError(f"Il seriale {codice} di {prodotto} è già in magazzino.")
        risultato.append((lotto, q))
    return risultato


def saldo(lotto, magazzino=None):
    qs = Movimento.objects.filter(lotto=lotto)
    if magazzino is not None:
        qs = qs.filter(magazzino=magazzino)
    return qs.aggregate(t=Sum("quantita"))["t"] or Decimal(0)


def disponibili(prodotto, magazzino):
    """Lotti con giacenza nel magazzino, prima quelli che scadono prima (FEFO), poi i più vecchi; niente scaduti."""
    oggi = timezone.localdate()
    saldi = dict(Movimento.objects.filter(prodotto=prodotto, magazzino=magazzino, lotto__isnull=False)
                 .values_list("lotto").annotate(t=Sum("quantita")).filter(t__gt=0))
    lotti = Lotto.objects.filter(pk__in=saldi).exclude(scadenza__lt=oggi)
    ordinati = sorted(lotti, key=lambda l: (l.scadenza is None, l.scadenza or oggi, l.creato, l.pk))
    return [(l, saldi[l.pk]) for l in ordinati]


def per_uscita(riga, prodotto, magazzino):
    """[(lotto o None, quantità)] per uno scarico: i lotti scritti sulla riga o, per i lotti, quelli che scadono prima."""
    tipo = tracciamento(prodotto)
    if not tipo:
        return [(None, Decimal(riga.quantita))]
    coppie = leggi(riga.lotti, riga.quantita, prodotto)
    if coppie:
        risultato = []
        for codice, q in coppie:
            lotto = Lotto.objects.filter(prodotto=prodotto, codice=codice).first()
            if lotto is None:
                raise ValidationError(f"{prodotto}: il lotto o seriale {codice} non esiste.")
            if lotto.seriale and saldo(lotto, magazzino) < 1:
                raise ValidationError(f"Il seriale {codice} di {prodotto} non è in questo magazzino.")
            risultato.append((lotto, q))
        return risultato
    if tipo == Tracciamento.SERIALE:
        raise ValidationError(f"{prodotto} si segue per numero di serie: scrivi sulla riga quali escono.")
    resto, risultato = Decimal(riga.quantita), []
    for lotto, q in disponibili(prodotto, magazzino):
        presa = min(resto, q)
        risultato.append((lotto, presa))
        resto -= presa
        if resto <= 0:
            break
    if resto > 0:
        raise ValidationError(f"{prodotto}: nei lotti non scaduti mancano {resto:g} unità; scrivi i lotti sulla riga.")
    return risultato
