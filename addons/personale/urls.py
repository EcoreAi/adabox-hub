"""Pagine del Personale."""
from django.urls import path

from . import pagine

urlpatterns = [path("mie/", pagine.mie, name="mie"),
               path("organigramma/", pagine.organigramma, name="organigramma"),
               path("timbra/", pagine.chiosco, name="chiosco"),
               path("timbra/io/", pagine.timbra_io, name="timbra_io"),
               path("presenze/", pagine.presenze_mese, name="presenze"),
               path("dipendenti/<int:pk>/pin/", pagine.imposta_pin, name="imposta_pin")]
