"""Pagine del portale oltre alla gestione degli accessi: la home del cliente, invito e sospensione dal contatto."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("", pagine.home, name="home"),
    path("contatto/<int:pk>/invita/", pagine.invita_contatto, name="invita_contatto"),
    path("contatto/<int:pk>/revoca/", pagine.revoca_contatto, name="revoca_contatto"),
]
