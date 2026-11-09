"""Spedizione delle consegne e ricezione dei ricevimenti: i movimenti di magazzino nascono qui."""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from core import parametri, sequenze

from . import costi, lotti
from .models import Consegna, Movimento, Ricevimento, giacenza


def _negativa_ammessa(azienda):
    try:
        return parametri.leggi("magazzino.giacenza_negativa", azienda)
    except KeyError:
        return True


class _Parte:
    """Una riga da scaricare: la riga stessa, o un componente del kit della riga (senza lotti né ubicazione scritti)."""
    def __init__(self, riga, prodotto, quantita, propria):
        self.prodotto, self.quantita = prodotto, quantita
        self.lotti = riga.lotti if propria else ""
        self.ubicazione = riga.ubicazione if propria else None
        self.kit = None if propria else riga.prodotto


def parti_da_scaricare(righe):
    """Le righe con i kit esplosi nei componenti: ciò che esce davvero dal magazzino."""
    parti = []
    for r in righe:
        esploso = r.prodotto.esploso(r.quantita)
        propria = len(esploso) == 1 and esploso[0][0] == r.prodotto
        parti.extend(_Parte(r, p, q, propria) for p, q in esploso)
    return parti


def colli_suggeriti(consegna):
    """(colli, peso in kg o None) dalle confezioni dei prodotti: la confezione più grande che non supera la quantità,
    il resto in una confezione in più; i prodotti senza confezioni non contano."""
    import math
    colli, peso, con_peso = 0, Decimal(0), True
    for r in consegna.righe.select_related("prodotto").prefetch_related("prodotto__confezioni"):
        confezioni = sorted(r.prodotto.confezioni.all(), key=lambda c: c.quantita, reverse=True)
        if not confezioni:
            continue
        scelta = next((c for c in confezioni if c.quantita <= r.quantita), confezioni[-1])
        n = math.ceil(Decimal(r.quantita) / scelta.quantita)
        colli += n
        if scelta.peso is None:
            con_peso = False
        else:
            peso += scelta.peso * n
    return colli, (peso if con_peso and colli else None)


@transaction.atomic
def spedisci(consegna, utente=None):
    """DDT numerato e scarico di ogni riga (dei componenti, per i kit). Senza giacenze negative ammesse, controlla la
    disponibilità. Se i colli sono rimasti quelli di partenza, li suggeriscono le confezioni."""
    if consegna.stato != Consegna.BOZZA:
        raise ValidationError("La consegna non è da spedire.")
    righe = list(consegna.righe.select_related("prodotto"))
    if not righe:
        raise ValidationError("La consegna non ha righe.")
    parti = parti_da_scaricare(righe)
    if not _negativa_ammessa(consegna.azienda):
        bisogno = {}
        for p in parti:
            bisogno[p.prodotto] = bisogno.get(p.prodotto, Decimal(0)) + Decimal(p.quantita)
        mancanti = [f"{prodotto} (disponibili {giacenza(prodotto, consegna.magazzino)})"
                    for prodotto, q in bisogno.items() if giacenza(prodotto, consegna.magazzino) < q]
        if mancanti:
            raise ValidationError("Merce insufficiente: " + ", ".join(mancanti))
    ct = ContentType.objects.get_for_model(Consegna)
    piano = [(p, lotti.per_uscita(p, p.prodotto, consegna.magazzino)) for p in parti]      # prima tutti i controlli
    for p, scelte in piano:
        causale = f"Consegna a {consegna.cliente}" + (f" (kit {p.kit.nome})" if p.kit else "")
        for lotto, quantita in scelte:
            Movimento.objects.create(azienda=consegna.azienda, prodotto=p.prodotto, magazzino=consegna.magazzino,
                                     ubicazione=p.ubicazione, lotto=lotto, quantita=-quantita, tipo=Movimento.SCARICO,
                                     utente=utente, causale=causale[:200], content_type=ct, object_id=consegna.pk)
    campi = ["numero", "stato"]
    if consegna.colli == 1 and not consegna.peso:
        colli, peso = colli_suggeriti(consegna)
        if colli > 1:
            consegna.colli, consegna.peso = colli, peso
            campi += ["colli", "peso"]
    consegna.numero = sequenze.prossimo("magazzino.ddt", consegna.azienda)
    consegna.stato = Consegna.FATTO
    consegna.save(update_fields=campi)


def disponibili_kit(kit, magazzino=None):
    """Quanti kit si possono fare con la merce: il minimo, fra i componenti, di giacenza diviso quantità per kit."""
    componenti = list(kit.componenti.select_related("componente"))
    if not kit.kit or not componenti:
        return None
    return min(int(max(Decimal(giacenza(c.componente, magazzino)), Decimal(0)) // c.quantita) for c in componenti)


@transaction.atomic
def ricevi(ricevimento, utente=None):
    if ricevimento.stato != Ricevimento.BOZZA:
        raise ValidationError("Il ricevimento non è da ricevere.")
    righe = list(ricevimento.righe.select_related("prodotto"))
    if not righe:
        raise ValidationError("Il ricevimento non ha righe.")
    kit = [str(r.prodotto) for r in righe if r.prodotto.kit and r.prodotto.componenti.exists()]
    if kit:
        raise ValidationError(f"Un kit non ha giacenza propria: ricevi i suoi componenti ({', '.join(kit)}).")
    ct = ContentType.objects.get_for_model(Ricevimento)
    dall_ordine = costi_ordine(ricevimento)
    piano = [(r, lotti.per_entrata(r, r.prodotto)) for r in righe]
    for r, parti in piano:
        costo = r.costo if r.costo is not None else dall_ordine.get(r.prodotto_id)
        for lotto, quantita in parti:
            Movimento.objects.create(azienda=ricevimento.azienda, prodotto=r.prodotto, magazzino=ricevimento.magazzino,
                                     ubicazione=r.ubicazione, lotto=lotto, quantita=quantita, tipo=Movimento.CARICO,
                                     utente=utente, causale=f"Ricevimento da {ricevimento.fornitore}", content_type=ct,
                                     object_id=ricevimento.pk, costo_unitario=costo)
    ricevimento.stato = Ricevimento.FATTO
    ricevimento.save(update_fields=["stato"])


def costi_ordine(ricevimento):
    """{prodotto: costo unitario} dalle righe dell'ordine d'acquisto da cui nasce il ricevimento, al netto dello sconto
    (media pesata se il prodotto compare in più righe). Vuoto se il ricevimento non viene da un ordine d'acquisto."""
    ordine = ricevimento.origine
    if ordine is None or not hasattr(ordine, "fornitore") or not hasattr(ordine, "righe"):
        return {}
    somme = {}
    for r in ordine.righe.all():
        if not r.prodotto_id or r.prezzo is None or not r.quantita:
            continue
        netto = Decimal(r.prezzo) * (Decimal(100) - Decimal(getattr(r, "sconto", 0) or 0)) / Decimal(100)
        quantita, valore = somme.get(r.prodotto_id, (Decimal(0), Decimal(0)))
        somme[r.prodotto_id] = (quantita + r.quantita, valore + r.quantita * netto)
    return {pk: costi.q4(valore / quantita) for pk, (quantita, valore) in somme.items() if quantita}



@transaction.atomic
def trasferisci(prodotto, quantita, da_magazzino, a_magazzino, da_ubicazione=None, a_ubicazione=None, utente=None, causale="",
                lotto=None):
    """Sposta merce tra magazzini o ubicazioni: un'uscita e un'entrata di tipo trasferimento, al costo attuale."""
    quantita = Decimal(quantita)
    if quantita <= 0:
        raise ValidationError("La quantità da spostare deve essere positiva.")
    if prodotto.tipo != "bene":
        raise ValidationError("I servizi non si movimentano a magazzino.")
    for magazzino, ubicazione in ((da_magazzino, da_ubicazione), (a_magazzino, a_ubicazione)):
        if magazzino.azienda_id != prodotto.azienda_id or (ubicazione and ubicazione.magazzino_id != magazzino.pk):
            raise ValidationError("Magazzino o ubicazione non validi.")
    from .models import tracciamento
    if tracciamento(prodotto) and lotto is None:
        raise ValidationError(f"{prodotto} si segue per lotto o seriale: indica quale sposti.")
    if lotto is not None and (lotto.prodotto_id != prodotto.pk or (lotto.seriale and quantita != 1)):
        raise ValidationError("Lotto non valido per questo prodotto o quantità.")
    if (da_magazzino.pk, getattr(da_ubicazione, "pk", None)) == (a_magazzino.pk, getattr(a_ubicazione, "pk", None)):
        raise ValidationError("Partenza e arrivo coincidono.")
    disponibile = giacenza(prodotto, da_magazzino, da_ubicazione, lotto)
    if (not _negativa_ammessa(prodotto.azienda) or (lotto and lotto.seriale)) and disponibile < quantita:
        raise ValidationError(f"Merce insufficiente: disponibili {disponibile}.")
    testo = causale or f"Trasferimento {da_ubicazione or da_magazzino} → {a_ubicazione or a_magazzino}"
    comuni = {"azienda": prodotto.azienda, "prodotto": prodotto, "tipo": Movimento.TRASFERIMENTO, "utente": utente,
              "causale": testo[:200], "lotto": lotto}
    uscita = Movimento.objects.create(magazzino=da_magazzino, ubicazione=da_ubicazione, quantita=-quantita, **comuni)
    entrata = Movimento.objects.create(magazzino=a_magazzino, ubicazione=a_ubicazione,
                                       quantita=quantita, **comuni)
    return uscita, entrata
