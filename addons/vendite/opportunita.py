"""Preventivi e ordini nati da un'opportunità del CRM (solo se il CRM è installato: le vendite non ne dipendono).
L'ordine tiene il numero dell'opportunità; confermandolo, l'opportunità passa alla fase di vittoria."""
from django.core.exceptions import ValidationError

from core import chatter

from .models import OrdineVendita


def ordini_di(opportunita):
    return OrdineVendita.objects.filter(azienda=opportunita.azienda, opportunita_id=opportunita.pk).order_by("-data", "-pk")


def di(ordine):
    if not ordine.opportunita_id:
        return None
    from crm.models import Opportunita
    return Opportunita.objects.filter(pk=ordine.opportunita_id, azienda=ordine.azienda).first()


def crea_preventivo(opportunita, utente=None):
    if opportunita.contatto_id is None:
        raise ValidationError("Collega prima l'opportunità a un contatto: il preventivo va a un cliente.")
    if opportunita.stato == opportunita.PERSA:
        raise ValidationError("L'opportunità è persa: riaprila prima di fare un preventivo.")
    ordine = OrdineVendita.objects.create(azienda=opportunita.azienda, cliente=opportunita.contatto,
                                          commerciale=opportunita.commerciale or utente,
                                          riferimento_cliente=opportunita.titolo[:100], opportunita_id=opportunita.pk)
    chatter.scrivi(opportunita, utente, f"Creato il preventivo {ordine}.", tipo="nota")
    return ordine


def vinci(sender, ordine, utente=None, **kwargs):
    """Ordine confermato: l'opportunità aperta da cui nasce diventa vinta (prima fase di vittoria)."""
    from crm.models import FaseCrm
    opportunita = di(ordine)
    if opportunita is None or opportunita.stato != opportunita.APERTA:
        return
    fase = FaseCrm.objects.filter(vinta=True).order_by("ordine", "pk").first()
    if fase is None:
        return
    vecchi = chatter.valori(opportunita, ["fase", "stato"])
    opportunita.fase = fase
    if not opportunita.valore_atteso:
        opportunita.valore_atteso = ordine.imponibile
    opportunita.save()
    chatter.traccia(opportunita, vecchi, utente)
    chatter.scrivi(opportunita, utente, f"Vinta: confermato l'ordine {ordine.numero_ordine or ordine}.", tipo="nota")
