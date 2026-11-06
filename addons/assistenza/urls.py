"""Pagine dell'assistenza oltre alle viste di gestione: widget di segnalazione (pubblico) e portale clienti."""
from django.apps import apps
from django.urls import path

from . import sviluppo, widget

urlpatterns = [
    path("widget/conferma/<str:token>/", widget.conferma_email, name="widget_conferma"),
    path("widget/<str:chiave>/", widget.segnala, name="widget"),
    path("ticket/<int:pk>/compito/", sviluppo.crea_compito_vista, name="crea_compito"),
]

if apps.is_installed("portale"):                          # le pagine del portale clienti, con il modulo portale
    from . import portale

    urlpatterns += [
        path("portale/", portale.home, name="portale"),
        path("portale/nuovo/", portale.nuovo, name="portale_nuovo"),
        path("portale/progetti/", portale.progetti, name="portale_progetti"),
        path("portale/guida/", portale.guida, name="portale_guida"),
        path("portale/guida/cerca/", portale.guida_cerca, name="portale_guida_cerca"),
        path("portale/guida/<int:pk>/", portale.articolo, name="portale_articolo"),
        path("portale/guida/<int:pk>/utile/", portale.utile, name="portale_utile"),
        path("portale/ticket/<int:pk>/", portale.dettaglio, name="portale_ticket"),
        path("portale/ticket/<int:pk>/file/<int:allegato>/", portale.scarica, name="portale_file"),
    ]
