"""Pagine proprie della Fatturazione."""
from django.urls import path

from . import pagine, registro

urlpatterns = [path("da-ordine/<int:pk>/", pagine.da_ordine, name="da_ordine"),
               path("registro-iva/", registro.registro_iva, name="registro_iva")]
