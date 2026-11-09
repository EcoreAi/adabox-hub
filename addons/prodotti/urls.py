"""Pagine dei Prodotti."""
from django.urls import path

from . import pagine

urlpatterns = [path("immagine/<path:nome>", pagine.immagine, name="immagine")]
