"""Pagine proprie del Magazzino: giacenze, valore di magazzino, metodo di costo del prodotto."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("giacenze/", pagine.giacenze, name="giacenze"),
    path("valore/", pagine.valore, name="valore"),
    path("trasferisci/", pagine.trasferisci, name="trasferisci"),
    path("per-ubicazione/", pagine.per_ubicazione, name="per_ubicazione"),
    path("valore/ricalcola/", pagine.ricalcola, name="ricalcola"),
    path("prodotto/<int:pk>/metodo/", pagine.metodo_prodotto, name="metodo_prodotto"),
    path("prodotto/<int:pk>/tracciamento/", pagine.tracciamento_prodotto, name="tracciamento_prodotto"),
]
