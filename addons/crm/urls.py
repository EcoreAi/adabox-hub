"""Pagine del CRM oltre alle viste di gestione: l'invio pubblico dei moduli del sito."""
from django.urls import path

from . import modulo_web

urlpatterns = [path("modulo/<str:chiave>/", modulo_web.invia, name="modulo_web")]
