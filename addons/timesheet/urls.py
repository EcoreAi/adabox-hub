"""Pagine proprie del Timesheet, montate dal kernel sotto /timesheet/ (namespace timesheet)."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("settimana/", pagine.settimana, name="settimana"),
]
