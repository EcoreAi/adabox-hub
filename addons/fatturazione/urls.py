"""Pagine proprie della Fatturazione."""
from django.urls import path

from . import commercialista, pagine, registro, scadenzario_pagina

urlpatterns = [path("da-ordine/<int:pk>/", pagine.da_ordine, name="da_ordine"),
               path("fatture/<int:pk>/incasso/", pagine.incasso, name="incasso"),
               path("incassi/<int:pk>/annulla/", pagine.incasso_annulla, name="incasso_annulla"),
               path("fatture/<int:pk>/usa-credito/", pagine.usa_credito, name="usa_credito"),
               path("registro-iva/", registro.registro_iva, name="registro_iva"),
               path("scadenzario/", scadenzario_pagina.scadenzario, name="scadenzario"),
               path("commercialista/", commercialista.pacchetto, name="commercialista")]

from django.apps import apps  # noqa: E402

if apps.is_installed("portale"):
    from . import portale

    urlpatterns += [
        path("portale/", portale.fatture, name="portale_fatture"),
        path("portale/<int:pk>/pdf/", portale.pdf, name="portale_pdf"),
    ]
