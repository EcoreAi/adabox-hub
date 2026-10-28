"""Pagine dello SDI."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("invia/<int:pk>/", pagine.invia, name="invia"),
    path("trasmissione/<int:pk>/xml/", pagine.xml, name="xml"),
    path("trasmissione/<int:pk>/caricata/", pagine.caricata, name="caricata"),
    path("carica/", pagine.carica, name="carica"),
]
