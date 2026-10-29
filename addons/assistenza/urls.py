"""Pagine dell'assistenza oltre alle viste di gestione: widget di segnalazione (pubblico) e portale clienti."""
from django.urls import path

from . import portale, sviluppo, widget

urlpatterns = [
    path("widget/<str:chiave>/", widget.segnala, name="widget"),
    path("portale/", portale.home, name="portale"),
    path("portale/nuovo/", portale.nuovo, name="portale_nuovo"),
    path("portale/progetti/", portale.progetti, name="portale_progetti"),
    path("portale/ticket/<int:pk>/", portale.dettaglio, name="portale_ticket"),
    path("portale/ticket/<int:pk>/file/<int:allegato>/", portale.scarica, name="portale_file"),
    path("ticket/<int:pk>/compito/", sviluppo.crea_compito_vista, name="crea_compito"),
    path("contatto/<int:pk>/invita/", portale.invita_contatto, name="invita_contatto"),
    path("contatto/<int:pk>/revoca/", portale.revoca_contatto, name="revoca_contatto"),
]
