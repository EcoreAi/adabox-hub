"""Le operazioni della cassa: registrare un movimento, chiudere con il contato, e i collegamenti con incassi e rimborsi."""
import datetime
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Cassa, ChiusuraCassa, MovimentoCassa


def predefinita(azienda):
    if azienda is None:
        return None
    return Cassa.objects.filter(azienda=azienda, attiva=True, predefinita=True).first()


def casse_attive(azienda):
    return Cassa.objects.filter(azienda=azienda, attiva=True) if azienda else Cassa.objects.none()


def data_libera(cassa, data):
    """La data indicata, o il giorno dopo l'ultima chiusura se la cassa è già chiusa a quella data."""
    chiusa = cassa.ultima_chiusura()
    data = max(data, cassa.dal)
    if chiusa and data <= chiusa.data:
        return chiusa.data + datetime.timedelta(days=1)
    return data


def registra(cassa, importo, causale, data=None, descrizione="", controparte="", utente=None, documento=None, incasso=None):
    """Un movimento di cassa già controllato (data dopo l'ultima chiusura, segno secondo la causale)."""
    m = MovimentoCassa(azienda_id=cassa.azienda_id, cassa=cassa, importo=Decimal(importo), causale=causale,
                       data=data or timezone.localdate(), descrizione=descrizione[:200], controparte=controparte[:120],
                       utente=utente, incasso=incasso)
    if documento is not None:
        m.tipo_documento, m.id_documento = ContentType.objects.get_for_model(documento), documento.pk
    m.full_clean(exclude=["azienda"])
    m.save()
    return m


@transaction.atomic
def chiudi(cassa, data, contato, utente=None, nota=""):
    """La chiusura alla data: saldo atteso, contato, differenza come movimento; i movimenti fin lì restano bloccati."""
    cassa = Cassa.objects.select_for_update().get(pk=cassa.pk)
    precedente = cassa.ultima_chiusura()
    if precedente and data <= precedente.data:
        raise ValidationError(f"La cassa è già chiusa al {precedente.data:%d/%m/%Y}: scegli una data successiva.")
    if data > timezone.localdate():
        raise ValidationError("Non si chiude una giornata che non è ancora finita.")
    if data < cassa.dal:
        raise ValidationError(f"La cassa è in uso dal {cassa.dal:%d/%m/%Y}.")
    contato = Decimal(contato)
    if contato < 0:
        raise ValidationError("I contanti contati non possono essere negativi.")
    aperti = cassa.movimenti.filter(chiusura__isnull=True, data__lte=data)
    apertura = precedente.contato if precedente else cassa.saldo_iniziale
    entrate = aperti.filter(importo__gt=0).aggregate(t=Sum("importo"))["t"] or Decimal(0)
    uscite = -(aperti.filter(importo__lt=0).aggregate(t=Sum("importo"))["t"] or Decimal(0))
    atteso = cassa.saldo_al(data)
    chiusura = ChiusuraCassa.objects.create(azienda_id=cassa.azienda_id, cassa=cassa, data=data, apertura=apertura, entrate=entrate,
                                            uscite=uscite, atteso=atteso, contato=contato, differenza=contato - atteso,
                                            nota=nota[:300], utente=utente)
    aperti.update(chiusura=chiusura)
    if chiusura.differenza:
        MovimentoCassa.objects.create(azienda_id=cassa.azienda_id, cassa=cassa, data=data, causale=MovimentoCassa.DIFFERENZA,
                                      importo=chiusura.differenza, utente=utente, chiusura=chiusura,
                                      descrizione=("Eccedenza" if chiusura.differenza > 0 else "Ammanco") + f" alla chiusura del {data:%d/%m/%Y}")
    return chiusura


@transaction.atomic
def annulla_chiusura(chiusura):
    """Solo l'ultima chiusura si annulla: i movimenti tornano modificabili, la differenza registrata sparisce."""
    if chiusura != chiusura.cassa.ultima_chiusura():
        raise ValidationError("Si annulla solo l'ultima chiusura della cassa.")
    chiusura.movimenti.filter(causale=MovimentoCassa.DIFFERENZA).delete()
    chiusura.movimenti.update(chiusura=None)
    chiusura.delete()


# ---------- collegamenti

def incasso_salvato(sender, instance, created, **kwargs):
    from fatturazione.models import Fattura
    """Un incasso di fattura in contanti entra nella cassa predefinita dell'azienda (se c'è)."""
    if not created or instance.metodo != "contanti" or instance.tipo != "incasso" or instance.importo <= 0:
        return
    fattura = instance.scadenza.fattura
    cassa = predefinita(fattura.azienda)
    if cassa is None or MovimentoCassa.objects.filter(incasso=instance).exists():
        return
    importo = instance.importo if fattura.tipo != Fattura.NOTA_CREDITO else -instance.importo
    registra(cassa, importo, MovimentoCassa.INCASSO if importo > 0 else MovimentoCassa.ALTRO, data=data_libera(cassa, instance.data),
             descrizione=f"{fattura}", controparte=str(fattura.cliente)[:120], utente=instance.utente, incasso=instance)


def incasso_eliminato(sender, instance, **kwargs):
    """Annullare l'incasso toglie il movimento ancora aperto; uno già chiuso resta (i soldi c'erano) senza legame."""
    MovimentoCassa.objects.filter(incasso=instance, chiusura__isnull=True).delete()


def movimenti_del_documento(documento):
    tipo = ContentType.objects.get_for_model(documento)
    return MovimentoCassa.objects.filter(tipo_documento=tipo, id_documento=documento.pk)


def riepilogo(cassa, giorni=30):
    """Le cifre per la scheda: saldo, ultima chiusura, entrate e uscite non ancora chiuse."""
    aperti = cassa.movimenti.filter(chiusura__isnull=True)
    return {"saldo": cassa.saldo, "chiusura": cassa.ultima_chiusura(),
            "entrate": aperti.filter(importo__gt=0).aggregate(t=Sum("importo"))["t"] or Decimal(0),
            "uscite": -(aperti.filter(importo__lt=0).aggregate(t=Sum("importo"))["t"] or Decimal(0)),
            "da_chiudere": aperti.count(),
            "movimenti": list(cassa.movimenti.filter(Q(chiusura__isnull=True) | Q(data__gte=timezone.localdate() - datetime.timedelta(days=giorni)))
                              .select_related("incasso", "chiusura")[:50])}
