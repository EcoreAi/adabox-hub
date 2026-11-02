"""Pagine proprie del Timesheet, montate dal kernel sotto /timesheet/ (namespace timesheet)."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("settimana/", pagine.settimana, name="settimana"),
    path("cronometro/avvia/", pagine.cronometro_avvia, name="cronometro_avvia"),
    path("cronometro/ferma/", pagine.cronometro_ferma, name="cronometro_ferma"),
]
