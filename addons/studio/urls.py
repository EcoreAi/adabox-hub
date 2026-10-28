"""Pagine di Studio."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("", pagine.indice, name="indice"),
    path("esporta/", pagine.esporta, name="esporta"),
    path("importa/", pagine.importa, name="importa"),
    path("<slug:modulo>/<slug:slug>/", pagine.editor, name="editor"),
    path("<slug:modulo>/<slug:slug>/ripristina/", pagine.ripristina, name="ripristina"),
]
