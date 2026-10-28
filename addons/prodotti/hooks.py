"""Hook di installazione dei Prodotti."""
from decimal import Decimal

from django.contrib.auth.models import Group, User

from core import sequenze
from core.models import Azienda

DEMO = [
    ("Notebook 15 pollici", "bene", "Hardware", "pz", "899.00", "640.00", "22", "5"),
    ("Monitor 27 pollici", "bene", "Hardware", "pz", "289.00", "195.00", "22", "3"),
    ("Cavo HDMI 2 m", "bene", "Accessori", "pz", "12.90", "4.10", "22", "20"),
    ("Toner stampante", "bene", "Consumabili", "pz", "64.00", "38.00", "22", "10"),
    ("Installazione e configurazione", "servizio", "Servizi", "h", "55.00", "0", "22", "0"),
    ("Assistenza annuale", "servizio", "Servizi", "pz", "480.00", "0", "22", "0"),
    ("Corso di formazione", "servizio", "Servizi", "h", "70.00", "0", "N4", "0"),
]


def post_install(modulo):
    Group.objects.get(name="Prodotti / Utente").user_set.add(*User.objects.filter(is_active=True))


def demo(modulo):
    """Un piccolo catalogo nella prima azienda attiva e un listino rivenditori con uno sconto a scaglioni."""
    from fiscale.models import AliquotaIva

    from .models import Categoria, Listino, PrezzoListino, Prodotto, UnitaMisura
    azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
    for nome, tipo, categoria, unita, prezzo, costo, aliquota, scorta in DEMO:
        if Prodotto.objects.filter(azienda=azienda, nome=nome).exists():
            continue
        Prodotto.objects.create(
            azienda=azienda, nome=nome, tipo=tipo, codice=sequenze.prossimo("prodotti.prodotto", azienda),
            categoria=Categoria.objects.get_or_create(nome=categoria)[0], unita=UnitaMisura.objects.get(simbolo=unita),
            prezzo_vendita=Decimal(prezzo), costo=Decimal(costo), aliquota_iva=AliquotaIva.objects.get(codice=aliquota),
            scorta_minima=Decimal(scorta))
    rivenditori, creato = Listino.objects.get_or_create(azienda=azienda, nome="Rivenditori")
    if creato:
        for p in Prodotto.objects.filter(azienda=azienda, tipo=Prodotto.BENE):
            PrezzoListino.objects.create(listino=rivenditori, prodotto=p, prezzo=(p.prezzo_vendita * Decimal("0.85")).quantize(Decimal("0.01")))
            PrezzoListino.objects.create(listino=rivenditori, prodotto=p, quantita_minima=10,
                                         prezzo=(p.prezzo_vendita * Decimal("0.80")).quantize(Decimal("0.01")))
