"""Hook di installazione della Fatturazione."""
import datetime

from django.contrib.auth.models import Group, User
from django.utils import timezone

from core.models import Azienda


def post_install(modulo):
    Group.objects.get(name="Fatturazione / Utente").user_set.add(*User.objects.filter(is_active=True))


def demo(modulo):
    """Dati fiscali dell'azienda e una fattura per ogni ordine confermato: emesse, una incassata, una in bozza."""
    from fiscale.models import TerminePagamento
    from vendite.models import OrdineVendita

    from . import operazioni
    from .models import DatiFiscali, Fattura
    azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
    if Fattura.objects.filter(azienda=azienda).exists():
        return
    if not azienda.partita_iva:
        azienda.partita_iva = "01234567897"
        azienda.save(update_fields=["partita_iva"])
    DatiFiscali.objects.get_or_create(azienda=azienda, defaults={
        "iban": "IT60X0542811101000000123456", "banca": "Banca Demo", "rea_ufficio": "RM", "rea_numero": "123456"})
    termine = TerminePagamento.objects.order_by("pk").first()
    ordini = list(OrdineVendita.objects.filter(azienda=azienda, stato=OrdineVendita.CONFERMATO).order_by("data"))
    oggi = timezone.localdate()
    for i, ordine in enumerate(ordini):
        cliente = ordine.cliente
        if not (cliente.partita_iva or cliente.codice_fiscale):
            cliente.codice_fiscale = "RSSMRA80A01H501U"
            cliente.save(update_fields=["codice_fiscale"])
        fattura = operazioni.da_ordine(ordine)
        fattura.data = max(ordine.data, oggi - datetime.timedelta(days=40 - 10 * i))
        fattura.termine_pagamento = fattura.termine_pagamento or termine
        fattura.save(update_fields=["data", "termine_pagamento"])
        if i < len(ordini) - 1 or len(ordini) == 1:
            operazioni.emetti(fattura)
            if i == 0:
                for s in fattura.scadenze.all():
                    operazioni.incassa(s, fattura.data + datetime.timedelta(days=20))
