from django.urls import path

from . import pagine

urlpatterns = [
    path("da-fatturare/", pagine.da_fatturare, name="da_fatturare"),
    path("progetto/<int:pk>/fattura-ore/", pagine.fattura_ore, name="fattura_ore"),
    path("progetto/<int:pk>/fattura-corpo/", pagine.fattura_corpo, name="fattura_corpo"),
    path("progetto/<int:pk>/condizioni/", pagine.condizioni_progetto, name="condizioni_progetto"),
    path("progetto/<int:pk>/collega/", pagine.collega_fattura, name="collega_fattura"),
    path("ticket/<int:pk>/ore/", pagine.ore_ticket, name="ore_ticket"),
]
