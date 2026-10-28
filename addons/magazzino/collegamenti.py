"""Documenti di magazzino nati dagli ordini confermati (segnali di vendite e acquisti)."""
from django.contrib.contenttypes.models import ContentType

from .models import Consegna, Magazzino, Ricevimento, RigaConsegna, RigaRicevimento


def consegna_da_ordine(sender, ordine, utente=None, **kwargs):
    """Una consegna da spedire con i beni dell'ordine di vendita (i servizi non si consegnano)."""
    righe = [r for r in ordine.righe.select_related("prodotto") if r.prodotto_id and r.prodotto.tipo == "bene"]
    if not righe:
        return None
    consegna = Consegna.objects.create(
        azienda=ordine.azienda, magazzino=Magazzino.predefinito_per(ordine.azienda), cliente=ordine.cliente,
        riferimento=ordine.numero_ordine, origine_tipo=ContentType.objects.get_for_model(ordine), origine_id=ordine.pk)
    for r in righe:
        RigaConsegna.objects.create(consegna=consegna, prodotto=r.prodotto, descrizione=r.descrizione,
                                    quantita=r.quantita)
    return consegna


def ricevimento_da_ordine(sender, ordine, utente=None, **kwargs):
    righe = [r for r in ordine.righe.select_related("prodotto") if r.prodotto_id and r.prodotto.tipo == "bene"]
    if not righe:
        return None
    ricevimento = Ricevimento.objects.create(
        azienda=ordine.azienda, magazzino=Magazzino.predefinito_per(ordine.azienda), fornitore=ordine.fornitore,
        riferimento=ordine.numero, origine_tipo=ContentType.objects.get_for_model(ordine), origine_id=ordine.pk)
    for r in righe:
        RigaRicevimento.objects.create(ricevimento=ricevimento, prodotto=r.prodotto, quantita=r.quantita)
    return ricevimento


def recupera_ordini(azienda):
    """Consegne e ricevimenti per gli ordini già confermati che non li hanno (es. installando il magazzino
    dopo vendite o acquisti). Restituisce quanti documenti ha creato."""
    from django.apps import apps
    creati = 0
    coppie = []
    if apps.is_installed("vendite"):
        from vendite.models import OrdineVendita
        coppie.append((OrdineVendita, Consegna, consegna_da_ordine))
    if apps.is_installed("acquisti"):
        from acquisti.models import OrdineAcquisto
        coppie.append((OrdineAcquisto, Ricevimento, ricevimento_da_ordine))
    for modello_ordine, modello_documento, crea in coppie:
        tipo = ContentType.objects.get_for_model(modello_ordine)
        con_documento = modello_documento.objects.filter(origine_tipo=tipo).values_list("origine_id", flat=True)
        for ordine in modello_ordine.objects.filter(azienda=azienda, stato="confermato").exclude(pk__in=con_documento):
            creati += crea(modello_ordine, ordine) is not None
    return creati


def di(origine, modello):
    """I documenti di magazzino nati da un ordine."""
    return modello.objects.filter(origine_tipo=ContentType.objects.get_for_model(origine), origine_id=origine.pk)
