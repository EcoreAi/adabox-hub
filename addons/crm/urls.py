"""Pagine del CRM oltre alle viste di gestione: l'invio pubblico dei moduli del sito."""
from django.urls import path

from . import modulo_web, pagine

urlpatterns = [path("modulo/<str:chiave>/", modulo_web.invia, name="modulo_web"),
               path("risultati/", pagine.risultati, name="risultati"),
               path("previsione/", pagine.previsione, name="previsione")]
