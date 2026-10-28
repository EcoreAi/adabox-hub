"""Pagine proprie del Magazzino (la situazione delle giacenze)."""
from django.urls import path

from . import pagine

urlpatterns = [path("giacenze/", pagine.giacenze, name="giacenze")]
