"""Pagine proprie della Fatturazione."""
from django.urls import path

from . import pagine, registro

urlpatterns = [path("da-ordine/<int:pk>/", pagine.da_ordine, name="da_ordine"),
               path("fatture/<int:pk>/incasso/", pagine.incasso, name="incasso"),
               path("incassi/<int:pk>/annulla/", pagine.incasso_annulla, name="incasso_annulla"),
               path("registro-iva/", registro.registro_iva, name="registro_iva")]
