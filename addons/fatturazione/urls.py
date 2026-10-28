"""Pagine proprie della Fatturazione."""
from django.urls import path

from . import pagine

urlpatterns = [path("da-ordine/<int:pk>/", pagine.da_ordine, name="da_ordine")]
