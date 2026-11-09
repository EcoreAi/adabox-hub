"""Pagine del Personale."""
from django.urls import path

from . import pagine, profilo, turni

urlpatterns = [path("mie/", pagine.mie, name="mie"),
               path("organigramma/", pagine.organigramma, name="organigramma"),
               path("timbra/", pagine.chiosco, name="chiosco"),
               path("timbra/io/", pagine.timbra_io, name="timbra_io"),
               path("presenze/", pagine.presenze_mese, name="presenze"),
               path("dipendenti/<int:pk>/pin/", pagine.imposta_pin, name="imposta_pin"),
               path("profilo/", profilo.profilo, name="profilo"),
               path("turni/", turni.griglia, name="turni"),
               path("documento/<int:pk>/", profilo.documento, name="documento"),
               path("richieste/<int:pk>/decidi/", profilo.decidi, name="richiesta_decidi")]
