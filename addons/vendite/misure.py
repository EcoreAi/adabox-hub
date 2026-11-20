"""Misure aziendali delle Vendite (core.misure): ordinato e preventivi aperti."""
from core.misure import Componente, Misura, registra

from .models import OrdineVendita

APERTI = {"stato__in": [OrdineVendita.BOZZA, OrdineVendita.INVIATO]}

registra(Misura(
    nome="vendite.ordinato", etichetta="Ordinato",
    definizione="imponibile degli ordini di vendita confermati (IVA esclusa), per data dell'ordine",
    sinonimi=("ordini", "ordini confermati", "portafoglio ordini"),
    raggruppamenti={"cliente": "cliente", "commerciale": "commerciale", "settimana": "data:settimana", "mese": "data:mese",
                    "anno": "data:anno"},
    periodo_su="data",
    componenti=(Componente("vendite.ordini", "sum:imponibile", {"stato": OrdineVendita.CONFERMATO}),)))

registra(Misura(
    nome="vendite.preventivi_aperti", etichetta="Preventivi aperti", unita="",
    definizione="numero di preventivi ancora in bozza o inviati al cliente e non confermati",
    sinonimi=("offerte aperte",), raggruppamenti={"cliente": "cliente"},
    componenti=(Componente("vendite.ordini", "count", APERTI),)))

registra(Misura(
    nome="vendite.valore_preventivi_aperti", etichetta="Valore dei preventivi aperti",
    definizione="imponibile dei preventivi ancora in bozza o inviati al cliente e non confermati",
    raggruppamenti={"cliente": "cliente"},
    componenti=(Componente("vendite.ordini", "sum:imponibile", APERTI),)))
