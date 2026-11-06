"""Pagine dei pagamenti online oltre alla gestione: link firmato, ritorno, pagamento simulato, webhook, portale."""
from django.apps import apps
from django.urls import path

from . import pagine

urlpatterns = [
    path("fattura/<str:token>/", pagine.fattura, name="fattura"),
    path("esito/<int:pk>/<str:firma>/", pagine.esito, name="esito"),
    path("simulato/<int:pk>/", pagine.finto, name="finto"),
    path("webhook/<int:pk>/", pagine.webhook, name="webhook"),
]

if apps.is_installed("portale"):
    urlpatterns += [path("portale/paga/<int:pk>/", pagine.paga_dal_portale, name="paga_portale")]
