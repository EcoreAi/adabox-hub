"""Pagine delle Note spese."""
from django.urls import path

from . import pagine

urlpatterns = [path("ricevuta/<int:pk>/", pagine.ricevuta, name="ricevuta"),
               path("riaddebiti/", pagine.riaddebiti, name="riaddebiti"),
               path("rimborso/<int:pk>/", pagine.rimborso, name="rimborso")]
