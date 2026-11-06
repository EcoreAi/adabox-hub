"""Pagine proprie degli Acquisti, oltre alle viste dei modelli."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("riordino/", pagine.riordino, name="riordino"),
    path("riordino/crea/", pagine.riordino_crea, name="riordino_crea"),
    path("valutazione/", pagine.valutazione, name="valutazione"),
    path("gare/<int:pk>/aggiudica/<int:ordine>/", pagine.aggiudica, name="aggiudica"),
    path("collega-fattura/", pagine.collega_fattura, name="collega_fattura"),
    path("scollega-fattura/<int:pk>/", pagine.scollega_fattura, name="scollega_fattura"),
]
