"""Pagine proprie del Calendario, oltre alle viste dei modelli: la prenotazione online."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("prenota/<slug:codice>/", pagine.prenota, name="prenota"),
    path("prenotazione/<str:token>/", pagine.prenotazione, name="prenotazione"),
]
