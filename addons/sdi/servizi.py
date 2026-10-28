"""Invio di una fattura allo SDI: XML, validazione con lo schema, trasmissione col canale dell'azienda."""
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from core import chatter
from fatturazione import fatturapa
from fatturazione.models import Fattura

from . import canali, validazione
from .models import Trasmissione

IN_CORSO = {Trasmissione.PRONTA, Trasmissione.INVIATA} | Trasmissione.CONCLUSI


def ultima(fattura):
    return fattura.trasmissioni.order_by("-pk").first()


def puo_inviare(fattura):
    t = ultima(fattura)
    return fattura.stato == Fattura.EMESSA and (t is None or t.stato not in IN_CORSO | {Trasmissione.RIFIUTATA})


def invia(fattura, utente=None, canale=None):
    """Crea la trasmissione e la passa al canale. ValidationError con i motivi se non si può."""
    if fattura.stato != Fattura.EMESSA:
        raise ValidationError("Si invia solo una fattura emessa.")
    precedente = ultima(fattura)
    if precedente is not None and precedente.stato in IN_CORSO | {Trasmissione.RIFIUTATA}:
        raise ValidationError(f"La fattura ha già una trasmissione ({precedente.get_stato_display().lower()}).")
    with transaction.atomic():
        if precedente is not None:                     # dopo uno scarto: nuovo progressivo, nuovo nome di file
            fattura.progressivo_invio = ""
            fattura.save(update_fields=["progressivo_invio"])
        nome, xml = fatturapa.genera(fattura)
        errori = validazione.errori(xml)
        if errori:
            raise ValidationError(["L'XML non rispetta lo schema FatturaPA:", *errori])
        t = Trasmissione.objects.create(azienda=fattura.azienda, fattura=fattura, nome_file=nome,
                                        file=ContentFile(xml, name=nome),
                                        canale=(canale or canali.per_azienda(fattura.azienda)).nome)
    canale = canale or canali.per_azienda(fattura.azienda)
    try:
        messaggio = canale.invia(t)
    except Exception as e:                             # rete, credenziali PEC...: resta traccia e si riprova
        t.stato, t.errori = Trasmissione.ERRORE, [{"codice": "invio", "descrizione": str(e)}]
        t.save(update_fields=["stato", "errori"])
        chatter.scrivi(fattura, utente, f"Invio allo SDI non riuscito: {e}", tipo="nota")
        raise ValidationError(f"Invio non riuscito: {e}")
    chatter.scrivi(fattura, utente, f"Fattura elettronica {nome}: {messaggio}", tipo="nota")
    return t, messaggio


def segna_caricata(trasmissione, utente=None):
    """Canale manuale: l'XML è stato caricato sul portale; da qui si attende la notifica."""
    from django.utils import timezone
    trasmissione.stato, trasmissione.inviata_il = Trasmissione.INVIATA, timezone.now()
    trasmissione.save(update_fields=["stato", "inviata_il"])
    chatter.scrivi(trasmissione.fattura, utente, f"{trasmissione.nome_file} caricato sul portale dello SDI.", tipo="nota")
