"""Pagine dell'helpdesk oltre alle viste di gestione: valutazione dal link e guida online, senza accesso."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("valuta/<str:token>/", pagine.valuta, name="valuta"),
    path("guida/", pagine.guida, name="guida"),
    path("guida/cerca/", pagine.guida_cerca, name="guida_cerca"),
    path("guida/<int:pk>/", pagine.articolo, name="guida_articolo"),
    path("guida/<int:pk>/utile/", pagine.guida_utile, name="guida_utile"),
]
