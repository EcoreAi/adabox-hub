"""Pagella dei fornitori: puntualità, completezza, tempi, resi e fatture coerenti con ciò che è arrivato.
Tutto calcolato dagli ordini confermati del periodo: nessun voto inserito a mano."""
from collections import defaultdict
from decimal import Decimal

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.utils import timezone

from . import riscontro
from .models import FatturaOrdine, OrdineAcquisto, RigaAcquisto


def _percento(parte, totale):
    return round(float(parte) * 100 / float(totale)) if totale else None


def _documenti(azienda, ordini_id):
    """({ordine: [date dei ricevimenti chiusi]}, {ordine: ricevuto}, {ordine: reso}) senza una query per ordine."""
    if not apps.is_installed("magazzino") or not ordini_id:
        return {}, {}, {}
    from magazzino.models import Consegna, Ricevimento, RigaConsegna, RigaRicevimento
    tipo = ContentType.objects.get_for_model(OrdineAcquisto)
    date = defaultdict(list)
    for origine, data in (Ricevimento.objects.filter(azienda=azienda, origine_tipo=tipo, origine_id__in=ordini_id,
                                                     stato=Ricevimento.FATTO).values_list("origine_id", "data")):
        date[origine].append(data)
    ricevuto = {r["ricevimento__origine_id"]: r["t"] for r in RigaRicevimento.objects.filter(
        ricevimento__origine_tipo=tipo, ricevimento__origine_id__in=ordini_id, ricevimento__stato=Ricevimento.FATTO
    ).values("ricevimento__origine_id").annotate(t=Sum("quantita"))}
    reso = {r["consegna__origine_id"]: r["t"] for r in RigaConsegna.objects.filter(
        consegna__origine_tipo=tipo, consegna__origine_id__in=ordini_id, consegna__stato=Consegna.FATTO
    ).values("consegna__origine_id").annotate(t=Sum("quantita"))}
    return date, ricevuto, reso


def schede(azienda, dal, al):
    """Una riga per fornitore con ordini confermati nel periodo, dal maggior valore al minore."""
    oggi = timezone.localdate()
    ordini = list(OrdineAcquisto.objects.filter(azienda=azienda, stato=OrdineAcquisto.CONFERMATO, confermato_il__gte=dal,
                                                confermato_il__lte=al).select_related("fornitore"))
    id_ordini = [o.pk for o in ordini]
    date, ricevuto, reso = _documenti(azienda, id_ordini)
    beni = {r["ordine"]: r["t"] for r in RigaAcquisto.objects.filter(
        ordine__in=id_ordini, prodotto__tipo="bene").values("ordine").annotate(t=Sum("quantita"))}
    fatturato = {r["ordine"]: r["t"] for r in FatturaOrdine.objects.filter(ordine__in=id_ordini).values("ordine").annotate(t=Sum("importo"))}
    tolleranza = riscontro.tolleranza(azienda)
    gruppi = defaultdict(lambda: {"ordini": 0, "valore": Decimal(0), "in_tempo": 0, "misurati": 0, "giorni": [],
                                  "ordinato": Decimal(0), "arrivato": Decimal(0), "reso": Decimal(0),
                                  "fatture_ok": 0, "fatture": 0, "fornitore": None})
    for o in ordini:
        g = gruppi[o.fornitore_id]
        g["fornitore"] = o.fornitore
        g["ordini"] += 1
        g["valore"] += o.imponibile
        ordinato = beni.get(o.pk, Decimal(0))
        arrivato = ricevuto.get(o.pk, Decimal(0))
        netto = arrivato - reso.get(o.pk, Decimal(0))
        g["ordinato"] += ordinato
        g["arrivato"] += arrivato
        g["reso"] += reso.get(o.pk, Decimal(0))
        giorni = date.get(o.pk)
        if giorni and o.confermato_il:
            g["giorni"].append((max(giorni) - o.confermato_il).days)
        completo = ordinato > 0 and arrivato >= ordinato        # un reso successivo pesa sui resi, non sulla puntualità
        if o.consegna_prevista and ordinato > 0:
            if completo:
                g["misurati"] += 1
                g["in_tempo"] += bool(giorni) and max(giorni) <= o.consegna_prevista
            elif o.consegna_prevista < oggi:                      # scaduta e ancora incompleta: è in ritardo
                g["misurati"] += 1
        if o.pk in fatturato:
            g["fatture"] += 1
            valore_atteso = o.imponibile * min(netto / ordinato, Decimal(1)) if ordinato else o.imponibile
            g["fatture_ok"] += abs(fatturato[o.pk] - valore_atteso) <= valore_atteso * tolleranza / 100
    righe = []
    for g in gruppi.values():
        righe.append({"fornitore": g["fornitore"], "ordini": g["ordini"], "valore": g["valore"],
                      "puntualita": _percento(g["in_tempo"], g["misurati"]), "misurati": g["misurati"],
                      "completezza": min(_percento(g["arrivato"] - g["reso"], g["ordinato"]) or 0, 100) if g["ordinato"] else None,
                      "giorni": round(sum(g["giorni"]) / len(g["giorni"])) if g["giorni"] else None,
                      "resi": _percento(g["reso"], g["arrivato"]),
                      "fatture": _percento(g["fatture_ok"], g["fatture"])})
    return sorted(righe, key=lambda r: -r["valore"])
