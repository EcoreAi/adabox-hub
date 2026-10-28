"""Hook di installazione delle Note spese."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.utils import timezone

from core import sequenze
from core.models import Azienda


def post_install(modulo):
    Group.objects.get(name="Note spese / Dipendente").user_set.add(*User.objects.filter(is_active=True))


def demo(modulo):
    """Una nota da approvare e una rimborsata, sui dipendenti dei dati demo del Personale."""
    from personale.models import Dipendente

    from .models import CategoriaSpesa, NotaSpese, RigaSpesa
    azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
    dipendenti = list(Dipendente.objects.filter(azienda=azienda, responsabile__isnull=False)[:2])
    if not dipendenti or NotaSpese.objects.filter(azienda=azienda).exists():
        return
    oggi = timezone.localdate()
    vitto, km, treno = (CategoriaSpesa.objects.get(nome=n) for n in ("Vitto", "Rimborso chilometrico",
                                                                     "Treno, aereo, bus"))
    schema = [(dipendenti[0], "Trasferta Milano", NotaSpese.INVIATA, -5),
              (dipendenti[-1], "Visita cliente Torino", NotaSpese.RIMBORSATA, -30)]
    for dipendente, titolo, stato, giorni in schema:
        data = oggi + datetime.timedelta(days=giorni)
        nota = NotaSpese.objects.create(azienda=azienda, dipendente=dipendente, titolo=titolo,
                                        numero=sequenze.prossimo("spese.nota", azienda))
        ricevuta = lambda nome: ContentFile(b"%PDF-1.4 ricevuta dimostrativa", name=nome)   # noqa: E731
        RigaSpesa.objects.create(nota=nota, data=data, categoria=treno, descrizione="Frecciarossa A/R",
                                 importo=Decimal("89.80"), ricevuta=ricevuta("treno.pdf"))
        RigaSpesa.objects.create(nota=nota, data=data, categoria=vitto, descrizione="Pranzo con il cliente",
                                 importo=Decimal("32.50"), ricevuta=ricevuta("pranzo.pdf"))
        RigaSpesa.objects.create(nota=nota, data=data, categoria=km, descrizione="Stazione - cliente", km=Decimal(36))
        nota.ricalcola()
        nota.stato, nota.inviata_il = stato, timezone.now()
        if stato == NotaSpese.RIMBORSATA:
            nota.rimborsata_il = data + datetime.timedelta(days=10)
        nota.save(update_fields=["stato", "inviata_il", "rimborsata_il"])
