"""Hook di installazione dello SDI."""
from django.contrib.auth.models import Group, User

from core.models import Azienda


def post_install(modulo):
    Group.objects.get(name="SDI / Utente").user_set.add(*User.objects.filter(is_active=True))


def demo(modulo):
    """Le fatture emesse dei dati demo passano dal simulatore dello SDI (indirizzi di prova se mancano)."""
    from django.core.exceptions import ValidationError

    from fatturazione.models import Fattura

    from . import canali, servizi
    azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
    if azienda is None:
        return
    if not (azienda.indirizzo and azienda.citta and azienda.cap):
        azienda.indirizzo, azienda.cap, azienda.citta, azienda.provincia = "Via Roma 1", "00100", "Roma", "RM"
        azienda.save(update_fields=["indirizzo", "cap", "citta", "provincia"])
    for fattura in Fattura.objects.filter(azienda=azienda, stato=Fattura.EMESSA, trasmissioni__isnull=True):
        cliente = fattura.cliente
        if not (cliente.indirizzo and cliente.citta and cliente.cap):
            cliente.indirizzo, cliente.cap, cliente.citta = "Via Milano 10", "20100", "Milano"
            cliente.save(update_fields=["indirizzo", "cap", "citta"])
        try:
            servizi.invia(fattura, canale=canali.Prova())
        except ValidationError:
            continue
