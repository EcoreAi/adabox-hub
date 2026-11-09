"""Pagine proprie del Magazzino: giacenze, valore di magazzino, metodo di costo del prodotto."""
from django.urls import path

from . import conta, lettura, pagine, prelievo

urlpatterns = [
    path("giacenze/", pagine.giacenze, name="giacenze"),
    path("valore/", pagine.valore, name="valore"),
    path("anzianita/", pagine.anzianita, name="anzianita"),
    path("trasferisci/", pagine.trasferisci, name="trasferisci"),
    path("lettura/", lettura.inizio, name="lettura"),
    path("lettura/codice/", lettura.codice, name="lettura_codice"),
    path("lettura/sposta/", lettura.trasferimento, name="lettura_sposta"),
    path("lettura/inventario/<int:pk>/", lettura.inventario, name="lettura_inventario"),
    path("lettura/<slug:tipo>/<int:pk>/", lettura.documento, name="lettura_documento"),
    path("inventari/<int:pk>/conta/", conta.conta, name="inventario_conta"),
    path("consegna/<int:pk>/prelievo/", prelievo.prelievo, name="prelievo"),
    path("per-ubicazione/", pagine.per_ubicazione, name="per_ubicazione"),
    path("valore/ricalcola/", pagine.ricalcola, name="ricalcola"),
    path("prodotto/<int:pk>/metodo/", pagine.metodo_prodotto, name="metodo_prodotto"),
    path("prodotto/<int:pk>/tracciamento/", pagine.tracciamento_prodotto, name="tracciamento_prodotto"),
]
