"""Pagine del Personale."""
from django.urls import path

from . import pagine

urlpatterns = [path("mie/", pagine.mie, name="mie")]
