"""Pagine dell'assistente, montate dal kernel sotto /ai/ (namespace ai)."""
from django.urls import path
from django.views.generic import RedirectView

from . import flusso, pagine

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="ai:chat"), name="indice"),
    path("chat/", pagine.chat, name="chat"),
    path("chat/<int:pk>/", pagine.chat, name="conversazione"),
    path("chat/invia/", pagine.invia, name="invia"),
    path("chat/<int:pk>/invia/", pagine.invia, name="invia_conversazione"),
    path("chat/<int:pk>/preferita/", pagine.preferita, name="preferita"),
    path("chat/<int:pk>/elimina/", pagine.elimina, name="elimina"),
    path("flusso/<int:pk>/", flusso.flusso, name="flusso"),
    path("turno/<int:pk>/stop/", pagine.stop, name="stop"),
    path("proposta/<int:pk>/conferma/", pagine.conferma_proposta, name="conferma_proposta"),
    path("proposta/<int:pk>/annulla/", pagine.annulla_proposta, name="annulla_proposta"),
    path("licenza/", pagine.pagina_licenza, name="licenza"),
]
