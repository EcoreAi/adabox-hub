"""Hook di installazione degli Acquisti."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.utils import timezone

from core import sequenze
from core.models import Azienda


def post_install(modulo):
    Group.objects.get(name="Acquisti / Buyer").user_set.add(*User.objects.filter(is_active=True))


def demo(modulo):
    """Due ordini a un fornitore (creato se manca) per i beni presenti."""
    from contatti.models import Contatto
    from prodotti.models import Prodotto

    from .models import OrdineAcquisto, RigaAcquisto
    azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
    if OrdineAcquisto.objects.filter(azienda=azienda).exists():
        return
    fornitore = (Contatto.objects.filter(azienda=azienda, fornitore=True).first()
                 or Contatto.objects.create(azienda=azienda, nome="Fornitore Demo Spa", fornitore=True,
                                            email="ordini@fornitore.example"))
    beni = list(Prodotto.objects.filter(azienda=azienda, tipo="bene", attivo=True)[:3])
    if not beni:
        return
    oggi = timezone.localdate()
    for stato, giorni in [(OrdineAcquisto.BOZZA, -1), (OrdineAcquisto.CONFERMATO, -15)]:
        o = OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore, stato=stato,
                                          data=oggi + datetime.timedelta(days=giorni),
                                          consegna_prevista=oggi + datetime.timedelta(days=7),
                                          numero=sequenze.prossimo("acquisti.ordine", azienda),
                                          confermato_il=oggi if stato == OrdineAcquisto.CONFERMATO else None)
        for p in beni:
            RigaAcquisto.objects.create(ordine=o, prodotto=p, quantita=Decimal(10))
        o.ricalcola()
