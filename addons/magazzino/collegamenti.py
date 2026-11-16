"""Documenti di magazzino nati dagli ordini confermati (segnali di vendite e acquisti)."""
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from contatti.models import IndirizzoContatto
from core import chatter

from .models import Consegna, Magazzino, Ricevimento, RigaConsegna, RigaRicevimento


def consegna_da_ordine(sender, ordine, utente=None, **kwargs):
    """Una consegna da spedire con i beni dell'ordine di vendita (i servizi non si consegnano)."""
    from core import esterni
    if esterni.gestito_da(ordine):                    # l'ordine arriva da un altro sistema: lì si spedisce
        return None
    righe = [r for r in ordine.righe.select_related("prodotto") if r.prodotto_id and r.prodotto.tipo == "bene"
             and not getattr(r, "diretta", False)]          # le righe in triangolazione le spedisce il fornitore
    if not righe:
        return None
    consegna = Consegna.objects.create(
        azienda=ordine.azienda, magazzino=Magazzino.predefinito_per(ordine.azienda), cliente=ordine.cliente,
        destinazione=getattr(ordine, "indirizzo_consegna", None) or IndirizzoContatto.predefinito_per(ordine.cliente, "consegna"),
        riferimento=ordine.numero_ordine, origine_tipo=ContentType.objects.get_for_model(ordine), origine_id=ordine.pk)
    for r in righe:
        RigaConsegna.objects.create(consegna=consegna, prodotto=r.prodotto, descrizione=r.descrizione,
                                    quantita=r.quantita_base if r.quantita_base is not None else r.quantita)
    return consegna


def ricevimento_da_ordine(sender, ordine, utente=None, **kwargs):
    if getattr(ordine, "consegna_a_id", None):              # triangolazione: la merce va dal fornitore al cliente
        return None
    righe = [r for r in ordine.righe.select_related("prodotto") if r.prodotto_id and r.prodotto.tipo == "bene"]
    if not righe:
        return None
    ricevimento = Ricevimento.objects.create(
        azienda=ordine.azienda, magazzino=Magazzino.predefinito_per(ordine.azienda), fornitore=ordine.fornitore,
        riferimento=ordine.numero, origine_tipo=ContentType.objects.get_for_model(ordine), origine_id=ordine.pk)
    for r in righe:
        RigaRicevimento.objects.create(ricevimento=ricevimento, prodotto=r.prodotto,
                                       quantita=r.quantita_base if r.quantita_base is not None else r.quantita)
    return ricevimento


def _annulla_documenti(ordine, modello, utente, parola_fatti, parola_annullati):
    """Annulla i documenti ancora aperti dell'ordine; se la merce si è già mossa, l'ordine non si annulla."""
    documenti = list(di(ordine, modello).exclude(stato=modello.ANNULLATO))
    fatti = [d for d in documenti if d.stato == modello.FATTO]
    if fatti:
        raise ValidationError(f"{ordine} non si può annullare: {parola_fatti} {', '.join(str(d) for d in fatti)}.")
    for documento in documenti:
        vecchi = chatter.valori(documento, ["stato"])
        documento.stato = modello.ANNULLATO
        documento.save(update_fields=["stato"])
        chatter.traccia(documento, vecchi, utente)
    return f"{parola_annullati}: {len(documenti)}." if documenti else None


def annulla_consegne(sender, ordine, utente=None, **kwargs):
    return _annulla_documenti(ordine, Consegna, utente, "merce già spedita con", "Consegne annullate")


def annulla_ricevimenti(sender, ordine, utente=None, **kwargs):
    return _annulla_documenti(ordine, Ricevimento, utente, "merce già ricevuta con", "Ricevimenti annullati")


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
