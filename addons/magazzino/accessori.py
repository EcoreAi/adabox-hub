"""Costi accessori di acquisto: ripartiti sui carichi dei ricevimenti, che diventano più cari; i costi di magazzino si
ricalcolano dai movimenti, quindi anche le uscite già fatte prendono il costo giusto."""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from . import costi
from .models import CostoAccessorio, Movimento, Ricevimento, RipartizioneCosto


def _carichi(costo):
    ct = ContentType.objects.get_for_model(Ricevimento)
    return list(Movimento.objects.filter(content_type=ct, object_id__in=costo.ricevimenti.values_list("pk", flat=True),
                                         quantita__gt=0).select_related("prodotto"))


def anteprima(costo):
    """[(movimento, peso del criterio, quota)] senza salvare nulla."""
    carichi = _carichi(costo)
    if not carichi:
        return []

    def misura(m):
        if costo.criterio == CostoAccessorio.QUANTITA:
            return Decimal(m.quantita)
        if costo.criterio == CostoAccessorio.PESO:
            return Decimal(m.quantita) * (m.prodotto.peso or 0)
        return Decimal(m.quantita) * (m.costo_unitario or 0)
    misure = [misura(m) for m in carichi]
    totale = sum(misure, Decimal(0))
    if not totale:
        raise ValidationError("Con questo criterio la merce vale zero (manca il costo o il peso dei prodotti): scegli un altro criterio.")
    quote = [(costo.importo * x / totale).quantize(Decimal("0.01")) for x in misure]
    quote[-1] += costo.importo - sum(quote, Decimal(0))         # i centesimi di arrotondamento all'ultima riga
    return list(zip(carichi, misure, quote))


@transaction.atomic
def applica(originale):
    costo = CostoAccessorio.objects.select_for_update().get(pk=originale.pk)
    if costo.stato != CostoAccessorio.BOZZA:
        raise ValidationError("Il costo è già applicato.")
    righe = anteprima(costo)
    if not righe:
        raise ValidationError("Scegli almeno un ricevimento già ricevuto.")
    prodotti = set()
    for m, _, quota in righe:
        RipartizioneCosto.objects.create(costo=costo, movimento=m, quota=quota, costo_prima=m.costo_unitario)
        nuovo = (Decimal(m.costo_unitario or 0) + quota / Decimal(m.quantita)).quantize(Decimal("0.0001"))
        Movimento.objects.filter(pk=m.pk).update(costo_unitario=nuovo, costo_fissato=True)
        prodotti.add(m.prodotto)
    for p in prodotti:
        costi.ricalcola(p)
    costo.stato = originale.stato = CostoAccessorio.APPLICATO
    costo.save(update_fields=["stato"])
    return righe


@transaction.atomic
def annulla(costo):
    if costo.stato != CostoAccessorio.APPLICATO:
        raise ValidationError("Il costo non è applicato.")
    prodotti = set()
    for r in costo.ripartizioni.select_related("movimento__prodotto"):
        m = r.movimento
        nuovo = (Decimal(m.costo_unitario or 0) - r.quota / Decimal(m.quantita)).quantize(Decimal("0.0001"))
        Movimento.objects.filter(pk=m.pk).update(costo_unitario=r.costo_prima if r.costo_prima is not None and nuovo < 0 else nuovo)
        prodotti.add(m.prodotto)
    costo.ripartizioni.all().delete()
    for p in prodotti:
        costi.ricalcola(p)
    costo.stato = CostoAccessorio.BOZZA
    costo.save(update_fields=["stato"])
