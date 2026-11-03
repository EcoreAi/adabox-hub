"""La conferma dell'ordine e la risposta del cliente al preventivo online."""
import datetime
import hashlib
import json

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core import chatter, modelli_email, sequenze
from core.models import Messaggio
from core.viste.gruppi import numero

from .models import OrdineVendita
from .segnali import ordine_confermato

SALE_LINK = "vendite.preventivo"
GIORNI_LINK = 90         # se il preventivo non dice fino a quando vale


def conferma(ordine, utente=None):
    """Numero d'ordine e segnale per magazzino e fatture. Chi chiama controlla che sia confermabile."""
    vecchi = chatter.valori(ordine, ["stato"])
    ordine.stato, ordine.confermato_il = OrdineVendita.CONFERMATO, timezone.localdate()
    ordine.numero_ordine = sequenze.prossimo("vendite.ordine", ordine.azienda)
    ordine.save(update_fields=["stato", "confermato_il", "numero_ordine"])
    chatter.traccia(ordine, vecchi, utente)
    ordine_confermato.send(sender=OrdineVendita, ordine=ordine, utente=utente)


def impronta(ordine):
    """Cambia se cambia ciò che il cliente accetta: un link vecchio non vale per un documento diverso."""
    dati = [ordine.cliente_id, str(ordine.totale), ordine.note,
            [[r.descrizione, str(r.quantita), str(r.prezzo), str(r.sconto), r.aliquota_id] for r in ordine.righe.all()]]
    return hashlib.sha256(json.dumps(dati, sort_keys=True).encode()).hexdigest()[:32]


def link(ordine):
    scade = timezone.localdate() + datetime.timedelta(days=GIORNI_LINK)
    token = signing.dumps([ordine.pk, impronta(ordine), scade.isoformat()], salt=SALE_LINK)
    return f"{settings.SITO_URL}{reverse('vendite:preventivo_online', args=[token])}"


def da_token(token):
    """(ordine, stato del link): valido, modificato o scaduto. (None, "invalido") se il link non è nostro."""
    try:
        pk, firma, scade = signing.loads(token, salt=SALE_LINK)
    except (signing.BadSignature, ValueError, TypeError):
        return None, "invalido"
    ordine = OrdineVendita.objects.select_related("cliente", "azienda").filter(pk=pk).first()
    if ordine is None:
        return None, "invalido"
    if ordine.risposta:
        return ordine, "risposto"
    if ordine.stato != OrdineVendita.INVIATO:
        return ordine, "chiuso"
    if impronta(ordine) != firma:
        return ordine, "modificato"
    limite = ordine.validita or datetime.date.fromisoformat(scade)
    return ordine, ("scaduto" if timezone.localdate() > limite else "valido")


def _risponde(ordine):
    """Il cliente risponde una volta sola e solo a un preventivo aperto: due clic insieme, ne passa uno."""
    ordine = OrdineVendita.objects.select_for_update().select_related("cliente", "azienda", "commerciale").get(pk=ordine.pk)
    if ordine.stato != OrdineVendita.INVIATO or ordine.risposta:
        raise ValidationError("Questo preventivo non è più aperto.")
    return ordine


def _avvisa_commerciale(ordine, esito, dettaglio):
    if ordine.commerciale_id and ordine.commerciale.email:
        modelli_email.messaggio("vendite.risposta", ordine.azienda, {
            "numero": str(ordine), "cliente": ordine.cliente.nome, "esito": esito, "dettaglio": dettaglio},
            [ordine.commerciale.email]).send(fail_silently=True)


def accetta(ordine, nome, ip=None):
    """Registra chi ha accettato, quando, da dove e che cosa; poi l'ordine prosegue come una conferma interna."""
    with transaction.atomic():
        ordine = _risponde(ordine)
        ordine.risposta, ordine.risposta_il, ordine.risposta_ip = OrdineVendita.ACCETTATO, timezone.now(), ip
        ordine.risposta_nome, ordine.risposta_impronta = nome, impronta(ordine)
        ordine.save(update_fields=["risposta", "risposta_il", "risposta_ip", "risposta_nome", "risposta_impronta"])
        conferma(ordine)
        chatter.scrivi(ordine, None, f"Preventivo {ordine.numero} accettato online da {nome} (totale {numero(ordine.totale)} €).",
                       tipo=Messaggio.NOTA)
    _avvisa_commerciale(ordine, "accettato", f"Da {nome}. Ordine {ordine.numero_ordine}, totale {numero(ordine.totale)} €.")
    if ordine.cliente.email:
        modelli_email.messaggio("vendite.accettato", ordine.azienda, {
            "numero": ordine.numero, "cliente": ordine.cliente.nome, "nome": nome, "ordine": ordine.numero_ordine,
            "totale": f"{numero(ordine.totale)} €", "data": f"{timezone.localtime(ordine.risposta_il):%d/%m/%Y %H:%M}"},
            [ordine.cliente.email]).send(fail_silently=True)
    return ordine


def rifiuta(ordine, motivo="", ip=None):
    with transaction.atomic():
        ordine = _risponde(ordine)
        ordine.risposta, ordine.risposta_il, ordine.risposta_ip = OrdineVendita.RIFIUTATO, timezone.now(), ip
        ordine.risposta_motivo = motivo
        ordine.save(update_fields=["risposta", "risposta_il", "risposta_ip", "risposta_motivo"])
        chatter.scrivi(ordine, None, f"Preventivo {ordine.numero} rifiutato online. {motivo}".strip(), tipo=Messaggio.NOTA)
    _avvisa_commerciale(ordine, "rifiutato", motivo or "Il cliente non ha indicato un motivo.")
    return ordine
