"""Misure aziendali delle Vendite (core.misure): ordinato, venduto per prodotto e preventivi aperti."""
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

# Le righe vendute (vista vendite.righe_vendute): stesse righe che fanno l'imponibile degli ordini confermati, quindi
# il totale del venduto coincide con l'ordinato; in più si raggruppa per prodotto.
RAGGRUPPAMENTI_RIGHE = {"prodotto": "prodotto", "cliente": "ordine__cliente", "commerciale": "ordine__commerciale",
                        "mese": "ordine__data:mese", "anno": "ordine__data:anno"}

registra(Misura(
    nome="vendite.venduto", etichetta="Venduto",
    definizione="importo delle righe degli ordini di vendita confermati (IVA esclusa), per prodotto, cliente o periodo; "
                "stesso totale dell'ordinato",
    sinonimi=("vendite per prodotto", "prodotti più venduti", "articoli più venduti", "fatturato per prodotto"),
    raggruppamenti=RAGGRUPPAMENTI_RIGHE, periodo_su="ordine__data",
    componenti=(Componente("vendite.righe_vendute", "sum:importo"),)))

registra(Misura(
    nome="vendite.quantita_venduta", etichetta="Quantità venduta", unita="",
    definizione="quantità nelle righe degli ordini di vendita confermati, nell'unità di ogni riga: da leggere per prodotto",
    sinonimi=("pezzi venduti", "prodotti più venduti per quantità"),
    raggruppamenti=RAGGRUPPAMENTI_RIGHE, periodo_su="ordine__data",
    componenti=(Componente("vendite.righe_vendute", "sum:quantita"),)))
