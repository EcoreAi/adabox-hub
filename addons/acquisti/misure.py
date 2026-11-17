"""Misura aziendale degli Acquisti (core.misure): acquistato."""
from core.misure import Componente, Misura, registra

from .models import OrdineAcquisto

registra(Misura(
    nome="acquisti.acquistato", etichetta="Acquistato",
    definizione="imponibile degli ordini di acquisto confermati (IVA esclusa), per data dell'ordine",
    sinonimi=("acquisti", "speso dai fornitori"),
    raggruppamenti={"fornitore": "fornitore", "mese": "data:mese", "anno": "data:anno"},
    periodo_su="data",
    componenti=(Componente("acquisti.ordini", "sum:imponibile", {"stato": OrdineAcquisto.CONFERMATO}),)))
