"""Pagine del portale oltre alla gestione degli accessi: la home del cliente, invito e sospensione dal contatto."""
from django.urls import path

from . import accesso_social, pagine

urlpatterns = [
    path("accedi/conferma/<str:token>/", accesso_social.conferma, name="accedi_conferma"),
    path("accedi/<str:tipo>/", accesso_social.accedi, name="accedi"),
    path("accedi/<str:tipo>/ritorno/", accesso_social.ritorno, name="accedi_ritorno"),
    path("", pagine.home, name="home"),
    path("contatto/<int:pk>/invita/", pagine.invita_contatto, name="invita_contatto"),
    path("contatto/<int:pk>/revoca/", pagine.revoca_contatto, name="revoca_contatto"),
]
