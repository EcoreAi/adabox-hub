"""Viaggi di consegna con il proprio mezzo: tappe in ordine, partenza (le consegne pronte si spediscono), esito di
ogni tappa, foglio di viaggio da stampare."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import operazioni
from .models import Consegna, TappaViaggio, Viaggio


@transaction.atomic
def parti(viaggio, utente=None):
    """Il viaggio parte: le consegne ancora aperte delle tappe si spediscono (DDT), e il mezzo diventa il vettore."""
    if viaggio.stato != Viaggio.PIANIFICATO:
        raise ValidationError("Il viaggio è già partito.")
    tappe = list(viaggio.tappe.select_related("consegna"))
    if not tappe:
        raise ValidationError("Aggiungi almeno una consegna.")
    for t in tappe:
        c = t.consegna
        if c.stato in Consegna.APERTI:
            if not c.vettore:
                c.vettore, c.trasporto_a_cura = f"Mezzo proprio {viaggio.mezzo}"[:120], "mittente"
                c.save(update_fields=["vettore", "trasporto_a_cura"])
            operazioni.spedisci(c, utente)
    viaggio.stato = Viaggio.IN_CORSO
    viaggio.save(update_fields=["stato"])


def esito(tappa, consegnata, nota=""):
    if tappa.viaggio.stato != Viaggio.IN_CORSO:
        raise ValidationError("Il viaggio non è in corso.")
    tappa.esito = TappaViaggio.CONSEGNATA if consegnata else TappaViaggio.NON_CONSEGNATA
    tappa.nota, tappa.alle = nota[:200], timezone.now()
    tappa.save(update_fields=["esito", "nota", "alle"])
    if not tappa.viaggio.tappe.filter(esito=TappaViaggio.DA_FARE).exists():
        tappa.viaggio.stato = Viaggio.CONCLUSO
        tappa.viaggio.save(update_fields=["stato"])


def consegne_da_caricare(viaggio):
    """Le consegne aperte del magazzino del viaggio non ancora in un viaggio."""
    gia = TappaViaggio.objects.filter(consegna__magazzino=viaggio.magazzino).exclude(viaggio__stato=Viaggio.CONCLUSO).values_list("consegna_id", flat=True)
    return Consegna.objects.filter(azienda=viaggio.azienda, magazzino=viaggio.magazzino, stato__in=Consegna.APERTI).exclude(pk__in=gia) \
        .select_related("cliente", "destinazione").order_by("data", "pk")
