"""Pagine dell'archivio dei documenti."""
from django.urls import path

from . import condivisioni, pagine

urlpatterns = [
    path("", pagine.archivio, name="archivio"),
    path("carica/", pagine.carica, name="carica"),
    path("cartella/", pagine.nuova_cartella, name="nuova_cartella"),
    path("azione/", pagine.azione, name="azione"),
    path("<int:pk>/anteprima/", pagine.anteprima, name="anteprima"),
    path("<int:pk>/scarica/", pagine.scarica, name="scarica"),
    path("<int:pk>/aggiorna/", pagine.modifica, name="modifica"),
    path("richiesta/<int:pk>/carica/", pagine.evadi, name="evadi"),
    path("condivisi/<str:token>/", condivisioni.pagina, name="condivisione"),
    path("condivisi/<str:token>/<int:pk>/", condivisioni.scarica, name="condivisione_scarica"),
]
