"""Pagine della qualità oltre alle viste di gestione: esecuzione di un collaudo e difetti."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("collaudi/<int:pk>/esegui/", pagine.esegui, name="esegui"),
    path("collaudi/<int:pk>/esecuzione/<int:esecuzione>/difetto/", pagine.difetto, name="difetto"),
]
