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
    if consegna.stato not in Consegna.APERTI:
        raise ValidationError("La consegna non è da spedire.")
    righe = list(consegna.righe.select_related("prodotto"))
    if not righe:
        raise ValidationError("La consegna non ha righe.")
    parti = parti_da_scaricare(righe)
    from . import qualita_merce
    mancano = qualita_merce.mancanti_per_spedire(consegna)
    if mancano:
        raise ValidationError("Prima della spedizione mancano i controlli qualità: " + ", ".join(f"{c.punto} su {c.prodotto}" for c in mancano))
    if not _negativa_ammessa(consegna.azienda):
        bisogno = {}
        for p in parti:
            bisogno[p.prodotto] = bisogno.get(p.prodotto, Decimal(0)) + Decimal(p.quantita)
        from .models import in_quarantena
        disponibile = {p: giacenza(p, consegna.magazzino) - in_quarantena(p, consegna.magazzino) for p in bisogno}
        mancanti = [f"{prodotto} (disponibili {disponibile[prodotto]})" for prodotto, q in bisogno.items() if disponibile[prodotto] < q]
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
    from . import qualita_merce
    qualita_merce.dopo_il_ricevimento(ricevimento)


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



def segna_pronta(consegna, utente=None):
    """La merce è preparata (prelevata e imballata): resta modificabile finché non si spedisce."""
    if consegna.stato != Consegna.BOZZA:
        raise ValidationError("Si segna pronta solo una consegna da spedire.")
    consegna.stato = Consegna.PRONTO
    consegna.save(update_fields=["stato"])
    from . import qualita_merce
    qualita_merce.mancanti_per_spedire(consegna)                 # i controlli prima della spedizione nascono qui


@transaction.atomic
def dividi(documento, quantita):
    """Evasione parziale: le righe del documento tengono le `quantita` indicate ({riga_id: q}, mancante = tutto) e il
    resto va in un documento nuovo da evadere dopo, con la stessa origine (l'ordine). Restituisce il residuo, o None."""
    if documento.stato not in documento.APERTI:
        raise ValidationError("Si divide solo un documento ancora aperto.")
    restano = []
    for r in documento.righe.all():
        tenuta = Decimal(quantita.get(r.pk, r.quantita))
        if tenuta < 0 or tenuta > r.quantita:
            raise ValidationError(f"{r.prodotto}: si tengono fra 0 e {r.quantita:g} pezzi.")
        if tenuta < r.quantita:
            restano.append((r, r.quantita - tenuta, tenuta))
    if not restano:
        return None
    if all(tenuta == 0 for _, _, tenuta in restano) and len(restano) == documento.righe.count():
        raise ValidationError("Non resterebbe niente da evadere adesso: lascia il documento com'è.")
    residuo = type(documento).objects.get(pk=documento.pk)
    residuo.pk = residuo.id = None
    residuo._state.adding = True
    residuo.stato = documento.BOZZA
    if isinstance(documento, Consegna):
        residuo.numero = ""
    residuo.note = (f"Residuo di {documento}. " + (documento.note or "")).strip()
    residuo.save()
    for r, resto, tenuta in restano:
        nuova = type(r).objects.get(pk=r.pk)
        nuova.pk = nuova.id = None
        nuova._state.adding = True
        nuova.quantita, nuova.lotti = resto, ""
        setattr(nuova, "consegna" if isinstance(documento, Consegna) else "ricevimento", residuo)
        nuova.save()
        if tenuta:
            r.quantita = tenuta
            r.save(update_fields=["quantita"])
        else:
            r.delete()
    return residuo


@transaction.atomic
def storna(documento, utente=None):
    """Annulla un documento già fatto con i movimenti opposti allo stesso costo. Una consegna già in fattura non si
    storna (prima la nota di credito); un ricevimento non si storna se la merce non c'è più e le giacenze negative
    non sono ammesse."""
    if documento.stato != documento.FATTO:
        raise ValidationError("Si storna solo un documento già spedito o ricevuto.")
    if isinstance(documento, Consegna) and documento.numero:
        from django.apps import apps
        if apps.is_installed("fatturazione"):
            from fatturazione.models import RiferimentoDDT
            fatture = RiferimentoDDT.objects.filter(numero=documento.numero, data=documento.data,
                                                     fattura__azienda=documento.azienda).exclude(fattura__stato="annullata")
            if fatture.exists():
                raise ValidationError(f"Il DDT {documento.numero} è nella {fatture.first().fattura}: prima fai la nota di credito.")
    ct = ContentType.objects.get_for_model(type(documento))
    movimenti = list(Movimento.objects.filter(content_type=ct, object_id=documento.pk).select_related("prodotto"))
    if isinstance(documento, Ricevimento) and not _negativa_ammessa(documento.azienda):
        mancanti = [str(m.prodotto) for m in movimenti if giacenza(m.prodotto, m.magazzino, m.ubicazione, m.lotto) < m.quantita]
        if mancanti:
            raise ValidationError("La merce non c'è più tutta: " + ", ".join(mancanti))
    for m in movimenti:
        Movimento.objects.create(azienda=m.azienda, prodotto=m.prodotto, magazzino=m.magazzino, ubicazione=m.ubicazione, lotto=m.lotto,
                                 quantita=-m.quantita, tipo=Movimento.CARICO if m.quantita < 0 else Movimento.SCARICO,
                                 causale=f"Storno di {documento}"[:200], utente=utente, content_type=ct, object_id=documento.pk,
                                 costo_unitario=(m.costo_unitario if m.costo_unitario is not None else costi.costo_corrente(m.prodotto))
                                 if m.quantita < 0 else None)
    documento.stato = documento.ANNULLATO
    documento.save(update_fields=["stato"])
    return len(movimenti)
