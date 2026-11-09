"""Il riscontro a tre: quanto si è ordinato, quanto è arrivato (al netto dei resi) e quanto è stato fatturato.
Magazzino e SDI sono facoltativi: senza magazzino tutto conta come ricevuto, senza SDI non ci sono fatture."""
import logging
import re
from decimal import ROUND_HALF_UP, Decimal

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from core import chatter, parametri

from .models import FatturaOrdine, OrdineAcquisto

log = logging.getLogger("acquisti.riscontro")
CENT = Decimal("0.01")


def _a_magazzino(riga):
    return bool(riga.prodotto_id and riga.prodotto.tipo == "bene")


def _quantita_mosse(ordine):
    """({prodotto: ricevuta}, {prodotto: resa}) dai documenti di magazzino chiusi dell'ordine."""
    if not apps.is_installed("magazzino"):
        return {}, {}
    from magazzino.models import Consegna, Ricevimento, RigaConsegna, RigaRicevimento
    tipo = ContentType.objects.get_for_model(ordine)
    ricevuta = (RigaRicevimento.objects.filter(ricevimento__origine_tipo=tipo, ricevimento__origine_id=ordine.pk,
                                               ricevimento__stato=Ricevimento.FATTO)
                .values("prodotto").annotate(t=Sum("quantita")))
    resa = (RigaConsegna.objects.filter(consegna__origine_tipo=tipo, consegna__origine_id=ordine.pk,
                                        consegna__stato=Consegna.FATTO)
            .values("prodotto").annotate(t=Sum("quantita")))
    return {r["prodotto"]: r["t"] for r in ricevuta}, {r["prodotto"]: r["t"] for r in resa}


def righe(ordine):
    """Per prodotto: ordinato, ricevuto, reso, netto, residuo e valore di ciò che è arrivato.
    Servizi e righe libere non passano dal magazzino: valgono per intero."""
    ricevuta, resa = _quantita_mosse(ordine)
    gestito = apps.is_installed("magazzino")
    gruppi = {}
    for r in ordine.righe.select_related("prodotto", "prodotto__unita"):
        if gestito and _a_magazzino(r):
            g = gruppi.setdefault(r.prodotto_id, {"nome": str(r.prodotto), "unita": r.prodotto.unita, "ordinato": Decimal(0),
                                                  "importo": Decimal(0), "a_magazzino": True, "prodotto_id": r.prodotto_id})
        else:
            g = gruppi.setdefault(f"riga-{r.pk}", {"nome": r.descrizione, "unita": "", "ordinato": Decimal(0),
                                                   "importo": Decimal(0), "a_magazzino": False, "prodotto_id": r.prodotto_id})
        g["ordinato"] += r.quantita_base if r.quantita_base is not None and g["a_magazzino"] else r.quantita
        g["importo"] += r.importo
    for g in gruppi.values():
        if g["a_magazzino"]:
            g["ricevuto"] = ricevuta.get(g["prodotto_id"], Decimal(0))
            g["reso"] = resa.get(g["prodotto_id"], Decimal(0))
            g["netto"] = g["ricevuto"] - g["reso"]
            g["residuo"] = max(g["ordinato"] - g["netto"], Decimal(0))
            g["eccesso"] = max(g["netto"] - g["ordinato"], Decimal(0))
            g["valore"] = (g["netto"] * g["importo"] / g["ordinato"]).quantize(CENT, ROUND_HALF_UP) if g["ordinato"] else Decimal(0)
        else:
            g.update(ricevuto=g["ordinato"], reso=Decimal(0), netto=g["ordinato"], residuo=Decimal(0), eccesso=Decimal(0),
                     valore=g["importo"])
    return list(gruppi.values())


def tolleranza(azienda):
    try:
        return Decimal(str(parametri.leggi("acquisti.tolleranza_riscontro", azienda)))
    except (KeyError, ArithmeticError):
        return Decimal(1)


def fatture_di(ordine):
    """[{collegamento, fattura}]: i collegamenti a fatture sparite non si mostrano."""
    if not apps.is_installed("sdi"):
        return []
    from sdi.models import FatturaPassiva
    collegamenti = list(ordine.fatture.all())
    fatture = FatturaPassiva.objects.filter(pk__in=[c.fattura_id for c in collegamenti]).in_bulk()
    return [{"collegamento": c, "fattura": fatture[c.fattura_id]} for c in collegamenti if c.fattura_id in fatture]


def riepilogo(ordine):
    """Lo stato dell'ordine sui tre lati, con l'esito del confronto tra fatturato e ricevuto."""
    dettaglio = righe(ordine)
    fatture = fatture_di(ordine)
    valore_ricevuto = sum((g["valore"] for g in dettaglio), Decimal(0))
    fatturato = sum((x["collegamento"].importo for x in fatture), Decimal(0))
    merce = [g for g in dettaglio if g["a_magazzino"]]
    if not merce or all(g["residuo"] == 0 for g in merce):
        ricevimento = "eccesso" if any(g["eccesso"] > 0 for g in merce) else "ricevuto"
    else:
        ricevimento = "parziale" if any(g["netto"] > 0 for g in merce) else "da_ricevere"
    scostamento = fatturato - valore_ricevuto
    margine = (valore_ricevuto * tolleranza(ordine.azienda) / 100).quantize(CENT, ROUND_HALF_UP)
    if not fatture:
        fatturazione = "da_fatturare"
    elif abs(scostamento) <= margine:
        fatturazione = "coerente"
    elif scostamento > 0:
        fatturazione = "oltre"
    else:
        fatturazione = "parziale"
    return {"righe": dettaglio, "fatture": fatture, "valore_ricevuto": valore_ricevuto, "fatturato": fatturato,
            "scostamento": scostamento, "stato_ricevimento": ricevimento, "stato_fatturazione": fatturazione,
            "ha_residuo": any(g["residuo"] > 0 for g in merce), "ha_netto": any(g["netto"] > 0 for g in merce)}


def fatture_collegabili(ordine):
    """Le fatture dello stesso fornitore non ancora imputate a questo ordine, le più recenti prima."""
    if not apps.is_installed("sdi"):
        return []
    from sdi.models import FatturaPassiva
    gia = ordine.fatture.values_list("fattura_id", flat=True)
    return FatturaPassiva.objects.filter(azienda=ordine.azienda, fornitore=ordine.fornitore).exclude(pk__in=gia)[:30]


def imponibile_con_segno(fattura):
    return -fattura.imponibile if fattura.nota_credito else fattura.imponibile


def imputato_altrove(fattura, ordine=None):
    qs = FatturaOrdine.objects.filter(fattura_id=fattura.pk)
    if ordine is not None:
        qs = qs.exclude(ordine=ordine)
    return qs.aggregate(t=Sum("importo"))["t"] or Decimal(0)


def collega(ordine, fattura, importo=None, utente=None, automatico=False):
    """Imputa la fattura all'ordine. Senza importo: ciò che della fattura non è ancora imputato ad altri ordini."""
    if fattura.azienda_id != ordine.azienda_id or fattura.fornitore_id != ordine.fornitore_id:
        raise ValidationError("La fattura è di un altro fornitore.")
    if ordine.stato != OrdineAcquisto.CONFERMATO:
        raise ValidationError("Si collegano le fatture solo agli ordini confermati.")
    totale = imponibile_con_segno(fattura)
    disponibile = totale - imputato_altrove(fattura, ordine)
    if importo is None:
        importo = disponibile
    if abs(importo) > abs(disponibile) or (importo and totale and (importo > 0) != (totale > 0)):
        raise ValidationError(f"Della fattura restano da imputare {disponibile} €.")
    collegamento, _ = FatturaOrdine.objects.update_or_create(
        ordine=ordine, fattura_id=fattura.pk, defaults={"importo": importo, "automatico": automatico})
    chatter.scrivi(ordine, utente, f"Fattura {fattura.numero} collegata per {importo} €.", tipo="nota")
    return collegamento


def scollega(collegamento, utente=None):
    ordine, fattura_id = collegamento.ordine, collegamento.fattura_id
    collegamento.delete()
    chatter.scrivi(ordine, utente, f"Scollegata la fattura (id {fattura_id}).", tipo="nota")


def _candidati(fattura, riferimenti):
    """Gli ordini confermati del fornitore citati dalla fattura: numero d'ordine, riferimento, DDT o causale."""
    ordini = OrdineAcquisto.objects.filter(azienda=fattura.azienda, fornitore=fattura.fornitore,
                                           stato=OrdineAcquisto.CONFERMATO)
    trovati = {}
    citati = [r for r in riferimenti.get("ordini", []) if r]
    if citati:
        for o in ordini.filter(numero__in=citati) | ordini.filter(riferimento_fornitore__in=citati):
            trovati[o.pk] = o
    ddt = [d for d in riferimenti.get("ddt", []) if d]
    if ddt and apps.is_installed("magazzino"):
        from magazzino.models import Ricevimento
        tipo = ContentType.objects.get_for_model(OrdineAcquisto)
        chiavi = Ricevimento.objects.filter(azienda=fattura.azienda, fornitore=fattura.fornitore, ddt_fornitore__in=ddt,
                                            origine_tipo=tipo).values_list("origine_id", flat=True)
        for o in ordini.filter(pk__in=list(chiavi)):
            trovati[o.pk] = o
    if not trovati and fattura.causale:
        parole = set(re.findall(r"[A-Za-z]+/\d{4}/\d+", fattura.causale))
        if parole:
            for o in ordini.filter(numero__in=parole):
                trovati[o.pk] = o
    return sorted(trovati.values(), key=lambda o: o.pk)


def fattura_ricevuta(sender, fattura, riferimenti=None, **kwargs):
    """Una fattura appena arrivata dallo SDI cerca da sola il suo ordine. Non deve mai far fallire l'arrivo:
    se qualcosa va storto la fattura si collega a mano."""
    try:
        with transaction.atomic():
            ordini = _candidati(fattura, riferimenti or {})
            for i, ordine in enumerate(ordini):
                # con più ordini citati: a ciascuno il valore ricevuto, all'ultimo ciò che resta della fattura
                importo = None
                if i < len(ordini) - 1:
                    totale = imponibile_con_segno(fattura)
                    resta = totale - imputato_altrove(fattura)
                    valore = riepilogo(ordine)["valore_ricevuto"]
                    importo = max(min(valore, resta), Decimal(0)) if totale > 0 else None
                collega(ordine, fattura, importo, automatico=True)
    except Exception:
        log.exception("Collegamento automatico della fattura %s non riuscito", fattura.pk)


def fattura_eliminata(sender, instance, **kwargs):
    FatturaOrdine.objects.filter(fattura_id=instance.pk).delete()


def _ricevimenti_aperti(ordine):
    from magazzino import collegamenti
    from magazzino.models import Ricevimento
    return collegamenti.di(ordine, Ricevimento).filter(stato=Ricevimento.BOZZA)


@transaction.atomic
def crea_residuo(ordine, utente=None):
    """Un ricevimento in bozza con ciò che manca. Se ce n'è già uno aperto, è quello da usare."""
    from magazzino.models import Magazzino, Ricevimento, RigaRicevimento
    aperto = _ricevimenti_aperti(ordine).first()
    if aperto is not None:
        return aperto
    mancanti = [g for g in righe(ordine) if g["a_magazzino"] and g["residuo"] > 0]
    if not mancanti:
        raise ValidationError("Non manca nulla da ricevere.")
    ricevimento = Ricevimento.objects.create(
        azienda=ordine.azienda, magazzino=Magazzino.predefinito_per(ordine.azienda), fornitore=ordine.fornitore,
        riferimento=ordine.numero, origine_tipo=ContentType.objects.get_for_model(ordine), origine_id=ordine.pk)
    for g in mancanti:
        RigaRicevimento.objects.create(ricevimento=ricevimento, prodotto_id=g["prodotto_id"], quantita=g["residuo"])
    chatter.scrivi(ordine, utente, "Creato il ricevimento di ciò che manca.", tipo="nota")
    return ricevimento


@transaction.atomic
def crea_reso(ordine, utente=None):
    """Un documento di reso (consegna con DDT) verso il fornitore con la merce arrivata; si corregge prima di spedire."""
    from magazzino import collegamenti
    from magazzino.models import Consegna, Magazzino, Ricevimento, RigaConsegna
    aperto = collegamenti.di(ordine, Consegna).filter(stato__in=Consegna.APERTI).first()
    if aperto is not None:
        return aperto
    arrivati = [g for g in righe(ordine) if g["a_magazzino"] and g["netto"] > 0]
    if not arrivati:
        raise ValidationError("Non c'è merce arrivata da rendere.")
    origine = collegamenti.di(ordine, Ricevimento).filter(stato=Ricevimento.FATTO).order_by("-data", "-pk").first()
    reso = Consegna.objects.create(
        azienda=ordine.azienda, magazzino=origine.magazzino if origine else Magazzino.predefinito_per(ordine.azienda),
        cliente=ordine.fornitore, causale_trasporto="reso", riferimento=f"Reso {ordine.numero}"[:60],
        origine_tipo=ContentType.objects.get_for_model(ordine), origine_id=ordine.pk)
    for g in arrivati:
        RigaConsegna.objects.create(consegna=reso, prodotto_id=g["prodotto_id"], quantita=g["netto"])
    chatter.scrivi(ordine, utente, "Creato il documento di reso al fornitore.", tipo="nota")
    return reso



def confronto_righe(fattura):
    """Le righe della fattura confrontate con gli ordini collegati: il prodotto si trova dal codice articolo (listino o
    righe d'ordine del fornitore) o dalla descrizione; poi prezzo unitario netto e quantità contro ordinato e ricevuto.
    [{riga, prodotto, prezzo_ordine, scarto_prezzo (%), ordinato, ricevuto, fatturato, esito}]: esito ok, prezzo,
    quantita, fuori (prodotto non negli ordini), sconosciuto (prodotto non trovato)."""
    from .models import VoceListino
    ordini = [c.ordine for c in FatturaOrdine.objects.filter(fattura_id=fattura.pk).select_related("ordine")]
    if not ordini:
        return []
    limite = tolleranza(fattura.azienda)
    righe_ordine, gruppi = {}, {}
    for o in ordini:
        for r in o.righe.select_related("prodotto").exclude(prodotto=None):
            righe_ordine.setdefault(r.prodotto_id, []).append(r)
        for g in righe(o):
            if g["prodotto_id"]:
                x = gruppi.setdefault(g["prodotto_id"], {"ordinato": Decimal(0), "ricevuto": Decimal(0)})
                x["ordinato"] += g["ordinato"]
                x["ricevuto"] += g["netto"] if g["a_magazzino"] else g["ordinato"]
    per_codice = {v.codice_fornitore.strip().upper(): v.prodotto_id for v in
                  VoceListino.objects.filter(azienda=fattura.azienda, fornitore=fattura.fornitore).exclude(codice_fornitore="")}
    for lista in righe_ordine.values():
        for r in lista:
            if r.codice_fornitore:
                per_codice.setdefault(r.codice_fornitore.strip().upper(), r.prodotto_id)
    fatturato, risultato = {}, []
    for rp in fattura.righe.order_by("numero_linea", "pk"):
        if rp.importo == 0 and not rp.quantita:
            continue
        prodotto_id = per_codice.get((rp.codice_articolo or "").strip().upper())
        if prodotto_id is None:
            testo = (rp.descrizione or "").lower()
            prodotto_id = next((pid for pid, lista in righe_ordine.items() if lista[0].prodotto.nome.lower() in testo), None)
        voce = {"riga": rp, "prodotto": None, "prezzo_ordine": None, "scarto_prezzo": None, "ordinato": None, "ricevuto": None,
                "fatturato": rp.quantita, "esito": "sconosciuto"}
        if prodotto_id is None:
            risultato.append(voce)
            continue
        lista = righe_ordine.get(prodotto_id)
        if not lista:
            from prodotti.models import Prodotto
            voce.update(prodotto=Prodotto.objects.filter(pk=prodotto_id).first(), esito="fuori")
            risultato.append(voce)
            continue
        r0 = lista[0]
        netto = (r0.prezzo * (100 - r0.sconto) / 100 / (r0.per_unita or 1)).quantize(Decimal("0.0001"))   # per unità del prodotto
        fatturato[prodotto_id] = fatturato.get(prodotto_id, Decimal(0)) + (rp.quantita or 0)
        scarto = ((Decimal(rp.prezzo) - netto) * 100 / netto).quantize(Decimal("0.1")) if netto else None
        g = gruppi.get(prodotto_id, {"ordinato": Decimal(0), "ricevuto": Decimal(0)})
        esito = "ok"
        if scarto is not None and scarto > limite:
            esito = "prezzo"
        elif fatturato[prodotto_id] > g["ricevuto"] * (1 + limite / 100):
            esito = "quantita"
        voce.update(prodotto=r0.prodotto, prezzo_ordine=netto, scarto_prezzo=scarto, ordinato=g["ordinato"], ricevuto=g["ricevuto"], esito=esito)
        risultato.append(voce)
    return risultato


def problemi(fattura):
    """Le righe fuori tolleranza (prezzo più alto o più quantità del ricevuto), in parole."""
    testi = []
    for v in confronto_righe(fattura):
        if v["esito"] == "prezzo":
            testi.append(f"{v['prodotto']}: prezzo {v['riga'].prezzo:.2f} € contro {v['prezzo_ordine']:.2f} € dell'ordine (+{v['scarto_prezzo']}%)")
        elif v["esito"] == "quantita":
            testi.append(f"{v['prodotto']}: fatturati {Decimal(v['fatturato']).normalize():f}, ricevuti {Decimal(v['ricevuto']).normalize():f}")
    return testi


def blocca_registrazione(sender, fattura, **kwargs):
    """Con il blocco acceso, una fattura fuori tolleranza non si registra: si verifica, si contesta o si forza."""
    try:
        acceso = parametri.leggi("acquisti.blocca_registrazione", fattura.azienda)
    except KeyError:
        acceso = False
    if not acceso:
        return
    elenco = problemi(fattura)
    if elenco:
        raise ValidationError("Fuori tolleranza rispetto all'ordine: " + "; ".join(elenco) + ". Contestala o chiedi a un responsabile di forzarla.")
