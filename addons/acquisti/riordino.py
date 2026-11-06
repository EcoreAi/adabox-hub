"""Che cosa riordinare. Previsto = giacenza + in arrivo − impegnato: chi è già stato ordinato non si riordina due volte,
quindi il lavoro del mattino si può ripetere senza doppioni. Si fermano le richieste in bozza: a decidere è il buyer."""
from collections import defaultdict
from decimal import Decimal

from django.apps import apps
from django.db import transaction
from django.db.models import Sum

from core import chatter
from core.models import Azienda
from prodotti.models import Prodotto

from . import listini
from .models import OrdineAcquisto, RegolaRiordino, RigaAcquisto
from .operazioni import _nuovo_ordine


def disponibile():
    return apps.is_installed("magazzino")


def _per_prodotto(qs, campo="prodotto", misura="quantita"):
    return {r[campo]: r["t"] or Decimal(0) for r in qs.values(campo).annotate(t=Sum(misura))}


def _quantita(azienda):
    from magazzino.models import Consegna, Movimento, Ricevimento, RigaConsegna, RigaRicevimento
    giacenze = _per_prodotto(Movimento.objects.filter(azienda=azienda))
    arrivo = _per_prodotto(RigaRicevimento.objects.filter(ricevimento__azienda=azienda, ricevimento__stato=Ricevimento.BOZZA))
    richieste = _per_prodotto(RigaAcquisto.objects.filter(
        ordine__azienda=azienda, prodotto__isnull=False,
        ordine__stato__in=[OrdineAcquisto.BOZZA, OrdineAcquisto.INVIATO, OrdineAcquisto.DA_APPROVARE], ordine__gara=None))
    impegni = _per_prodotto(RigaConsegna.objects.filter(consegna__azienda=azienda, consegna__stato=Consegna.BOZZA))
    return giacenze, arrivo, richieste, impegni


def proposte(azienda):
    """Una voce per ogni bene attivo sotto il punto di riordino, con il fornitore e la quantità da ordinare."""
    if not disponibile():
        return []
    giacenze, arrivo, richieste, impegni = _quantita(azienda)
    regole = {r.prodotto_id: r for r in RegolaRiordino.objects.filter(azienda=azienda).select_related("fornitore")}
    risultato = []
    for p in Prodotto.objects.filter(azienda=azienda, tipo=Prodotto.BENE, attivo=True).select_related("unita"):
        regola = regole.get(p.pk)
        punto = regola.punto_riordino if regola else p.scorta_minima
        obiettivo = regola.scorta_obiettivo if regola else p.scorta_minima
        if not regola and p.scorta_minima <= 0:
            continue
        giacenza = giacenze.get(p.pk, Decimal(0))
        in_arrivo = arrivo.get(p.pk, Decimal(0)) + richieste.get(p.pk, Decimal(0))
        impegnato = impegni.get(p.pk, Decimal(0))
        previsto = giacenza + in_arrivo - impegnato
        if previsto >= punto:
            continue
        quantita = obiettivo - previsto
        voce, fornitore = None, regola.fornitore if regola and regola.fornitore_id else None
        if fornitore is not None:
            minimo = listini.minimo(fornitore, p)
            quantita = max(quantita, minimo) if minimo else quantita
            voce = listini.voce(fornitore, p, quantita)
        else:
            voce, quantita = listini.scegli_fornitore(p, quantita)
            fornitore = voce.fornitore if voce else None
        risultato.append({"prodotto": p, "giacenza": giacenza, "in_arrivo": in_arrivo, "impegnato": impegnato,
                          "previsto": previsto, "punto": punto, "obiettivo": obiettivo, "quantita": quantita,
                          "fornitore": fornitore, "voce": voce, "regola": regola})
    return risultato


@transaction.atomic
def crea_richieste(azienda, voci, utente=None, nota="Creata dalle proposte di riordino."):
    """Una richiesta in bozza per fornitore. Le voci senza fornitore restano fuori. Restituisce gli ordini creati."""
    per_fornitore = defaultdict(list)
    for v in voci:
        if v["fornitore"] is not None:
            per_fornitore[v["fornitore"]].append(v)
    ordini = []
    for fornitore, gruppo in per_fornitore.items():
        ordine = _nuovo_ordine(azienda, fornitore, utente)
        for v in gruppo:
            RigaAcquisto.objects.create(ordine=ordine, prodotto=v["prodotto"], quantita=v["quantita"])
        ordine.ricalcola()
        chatter.scrivi(ordine, utente, nota, tipo="nota")
        ordini.append(ordine)
    return ordini


def automatico():
    """Lavoro del mattino: solo i prodotti con una regola che lo chiede esplicitamente."""
    if not disponibile():
        return 0
    creati = 0
    for azienda in Azienda.objects.filter(attiva=True):
        voci = [v for v in proposte(azienda) if v["regola"] is not None and v["regola"].automatica]
        creati += len(crea_richieste(azienda, voci, nota="Creata dal riordino automatico: controllala e inviala."))
    return creati
