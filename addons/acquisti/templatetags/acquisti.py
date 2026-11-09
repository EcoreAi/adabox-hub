"""Dati delle sezioni che gli Acquisti aggiungono ai dettagli (ordine, gara, contratto, fornitore, prodotto, fattura)."""
from decimal import Decimal

from django import template
from django.apps import apps

from acquisti import listini, operazioni, riscontro
from acquisti.models import FatturaOrdine, OrdineAcquisto

register = template.Library()


@register.simple_tag
def approvazioni_di(ordine):
    return list(ordine.approvazioni.select_related("decisa_da", "richiesta_da").order_by("-richiesta_il", "livello", "pk"))


@register.simple_tag
def riscontro_di(ordine):
    if ordine.stato != OrdineAcquisto.CONFERMATO:
        return None
    dati = riscontro.riepilogo(ordine)
    dati["collegabili"] = riscontro.fatture_collegabili(ordine)
    dati["sdi"] = apps.is_installed("sdi")
    dati["etichetta_ricevimento"] = {"da_ricevere": "Da ricevere", "parziale": "Ricevuto in parte", "ricevuto": "Ricevuto",
                                     "eccesso": "Ricevuto più dell'ordinato"}[dati["stato_ricevimento"]]
    dati["etichetta_fatturazione"] = {"da_fatturare": "Da fatturare", "coerente": "Fattura coerente con la merce",
                                      "oltre": "Fatturato più del ricevuto", "parziale": "Fatturato meno del ricevuto"}[dati["stato_fatturazione"]]
    return dati


@register.simple_tag
def avvisi_listino(ordine):
    """Righe sotto il minimo d'ordine del fornitore: solo un avviso, perché il minimo si può trattare."""
    if ordine.stato == OrdineAcquisto.ANNULLATO:
        return []
    avvisi = []
    for r in ordine.righe.exclude(prodotto=None).select_related("prodotto"):
        minimo = listini.minimo(ordine.fornitore, r.prodotto, ordine.data)
        if minimo and r.quantita < minimo:
            avvisi.append(f"{r.prodotto}: il minimo d'ordine del fornitore è {minimo:g}, qui sono {r.quantita:g}.")
    return avvisi


@register.simple_tag
def confronto_gara(gara):
    """Per ogni riga della gara il prezzo di ogni offerta, con il più basso in evidenza; in fondo i totali."""
    offerte = list(gara.offerte.exclude(stato=OrdineAcquisto.ANNULLATO).select_related("fornitore").prefetch_related("righe"))
    righe = []
    for rg in gara.righe.select_related("prodotto"):
        celle = []
        for o in offerte:
            trovata = next((r for r in o.righe.all() if (r.prodotto_id == rg.prodotto_id if rg.prodotto_id
                                                         else r.descrizione == rg.descrizione)), None)
            celle.append({"riga": trovata, "migliore": False})
        prezzi = [c["riga"].importo / c["riga"].quantita for c in celle if c["riga"] and c["riga"].importo > 0]
        if prezzi:
            minimo = min(prezzi)
            for c in celle:
                c["migliore"] = bool(c["riga"] and c["riga"].importo > 0 and c["riga"].importo / c["riga"].quantita == minimo)
        righe.append({"riga": rg, "celle": celle})
    positivi = [o.imponibile for o in offerte if o.imponibile > 0]
    migliore = min(positivi) if positivi else None
    colonne = [{"ordine": o, "migliore": o.imponibile == migliore and migliore is not None} for o in offerte]
    return {"colonne": colonne, "righe": righe}


@register.simple_tag
def residui_di(contratto):
    return operazioni.residui_contratto(contratto)


@register.simple_tag
def scheda_fornitore(contatto):
    return {"condizioni": listini.condizioni(contatto), "voci": contatto.listino_acquisto.count(),
            "contratti": contatto.contratti_quadro.filter(stato="attivo").count()}


@register.simple_tag
def listino_prodotto(prodotto):
    return list(prodotto.listino_acquisto.select_related("fornitore").order_by("quantita_minima", "prezzo")[:20])


@register.simple_tag
def ordini_di_fattura(fattura):
    collegamenti = list(FatturaOrdine.objects.filter(fattura_id=fattura.pk).select_related("ordine"))
    imponibile = riscontro.imponibile_con_segno(fattura)
    imputato = sum((c.importo for c in collegamenti), Decimal(0))
    aperti = OrdineAcquisto.objects.filter(azienda=fattura.azienda, fornitore=fattura.fornitore,
                                           stato=OrdineAcquisto.CONFERMATO).exclude(
        pk__in=[c.ordine_id for c in collegamenti]).order_by("-confermato_il", "-pk")[:30]
    return {"collegamenti": collegamenti, "da_imputare": imponibile - imputato, "aperti": aperti}


@register.simple_tag
def confronto_fattura(fattura):
    return riscontro.confronto_righe(fattura)
