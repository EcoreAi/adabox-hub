"""Pagine dell'archivio dei documenti."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("", pagine.archivio, name="archivio"),
    path("carica/", pagine.carica, name="carica"),
    path("cartella/", pagine.nuova_cartella, name="nuova_cartella"),
    path("azione/", pagine.azione, name="azione"),
    path("<int:pk>/anteprima/", pagine.anteprima, name="anteprima"),
    path("<int:pk>/scarica/", pagine.scarica, name="scarica"),
    path("<int:pk>/aggiorna/", pagine.modifica, name="modifica"),
]
