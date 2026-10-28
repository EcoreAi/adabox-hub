"""Hook di installazione delle Vendite."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.utils import timezone

from core import sequenze
from core.models import Azienda


def post_install(modulo):
    Group.objects.get(name="Vendite / Venditore").user_set.add(*User.objects.filter(is_active=True))


def demo(modulo):
    """Qualche preventivo e ordine sui clienti e prodotti presenti (creati se mancano)."""
    from contatti.models import Contatto
    from prodotti.models import Prodotto

    from .models import OrdineVendita, RigaVendita
    azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
    if OrdineVendita.objects.filter(azienda=azienda).exists():
        return
    clienti = list(Contatto.objects.filter(azienda=azienda, cliente=True, tipo="azienda")[:3])
    for nome in ["Cliente Demo Srl", "Studio Demo Associato", "Negozio Demo Snc"][len(clienti):]:
        clienti.append(Contatto.objects.create(azienda=azienda, nome=nome, cliente=True, email="demo@example.com"))
    prodotti = list(Prodotto.objects.filter(azienda=azienda, attivo=True)[:5])
    if not prodotti:
        prodotti = [Prodotto.objects.create(azienda=azienda, nome="Consulenza", tipo="servizio", prezzo_vendita=60),
                    Prodotto.objects.create(azienda=azienda, nome="Licenza software", prezzo_vendita=250)]
    oggi = timezone.localdate()
    schema = [(0, OrdineVendita.BOZZA, -2), (1, OrdineVendita.INVIATO, -10), (2, OrdineVendita.CONFERMATO, -20),
              (0, OrdineVendita.CONFERMATO, -45)]
    for i, (c, stato, giorni) in enumerate(schema):
        data = oggi + datetime.timedelta(days=giorni)
        o = OrdineVendita.objects.create(azienda=azienda, cliente=clienti[c], data=data, stato=stato,
                                         validita=data + datetime.timedelta(days=30),
                                         numero=sequenze.prossimo("vendite.preventivo", azienda))
        for j, p in enumerate(prodotti[i % 2:i % 2 + 3]):
            RigaVendita.objects.create(ordine=o, prodotto=p, quantita=Decimal(j + 1), sconto=Decimal(5 * (i % 2)))
        if stato == OrdineVendita.CONFERMATO:
            o.numero_ordine, o.confermato_il = sequenze.prossimo("vendite.ordine", azienda), data
            o.save(update_fields=["numero_ordine", "confermato_il"])
        o.ricalcola()
