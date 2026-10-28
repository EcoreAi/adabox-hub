"""Hook di installazione del Magazzino."""
from decimal import Decimal

from django.contrib.auth.models import Group, User

from core.models import Azienda


def post_install(modulo):
    from .models import Magazzino
    Group.objects.get(name="Magazzino / Operatore").user_set.add(*User.objects.filter(is_active=True))
    for azienda in Azienda.objects.filter(attiva=True):
        Magazzino.predefinito_per(azienda)


def demo(modulo):
    """Inventario iniziale dei beni (la metà sotto scorta, per vedere gli avvisi) e i documenti degli ordini
    confermati che ancora non li hanno."""
    from prodotti.models import Prodotto

    from . import collegamenti
    from .models import Magazzino, Movimento
    azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
    collegamenti.recupera_ordini(azienda)
    if Movimento.objects.filter(azienda=azienda).exists():
        return
    magazzino = Magazzino.predefinito_per(azienda)
    for i, p in enumerate(Prodotto.objects.filter(azienda=azienda, tipo=Prodotto.BENE, attivo=True)):
        quantita = (p.scorta_minima or Decimal(5)) * (Decimal(3) if i % 2 == 0 else Decimal("0.5"))
        Movimento.objects.create(azienda=azienda, prodotto=p, magazzino=magazzino, quantita=quantita,
                                 tipo=Movimento.RETTIFICA, causale="Inventario iniziale")
