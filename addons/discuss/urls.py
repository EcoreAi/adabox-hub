"""Pagine di Discuss."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("", pagine.home, name="home"),
    path("c/<int:pk>/", pagine.canale, name="canale"),
    path("c/<int:pk>/nuovi/", pagine.nuovi, name="nuovi"),
    path("c/<int:pk>/precedenti/", pagine.precedenti, name="precedenti"),
    path("c/<int:pk>/invia/", pagine.invia, name="invia"),
    path("c/<int:pk>/entra/", pagine.entra, name="entra"),
    path("c/<int:pk>/esci/", pagine.esci, name="esci"),
    path("c/<int:pk>/invita/", pagine.invita, name="invita"),
    path("c/<int:pk>/preferenze/", pagine.preferenze, name="preferenze"),
    path("m/<int:pk>/modifica/", pagine.modifica, name="modifica"),
    path("m/<int:pk>/elimina/", pagine.elimina, name="elimina"),
    path("allegato/<int:pk>/", pagine.allegato, name="allegato"),
    path("canale/nuovo/", pagine.nuovo_canale, name="nuovo_canale"),
    path("diretto/", pagine.diretto, name="diretto"),
    path("posta/", pagine.posta, name="posta"),
    path("posta/lette/", pagine.tutte_lette, name="tutte_lette"),
    path("notifica/<int:pk>/", pagine.apri_notifica, name="notifica"),
    path("contatore/", pagine.contatore, name="contatore"),
]
