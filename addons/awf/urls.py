"""Pagine di AWF, montate dal kernel sotto /awf/ (namespace awf). Il server MCP e il webhook di Agate non usano la
sessione: si autenticano con il bearer e con la firma."""
from django.urls import path
from django.views.generic import RedirectView

from . import mcp, pagine, webhook

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="awf:stato"), name="indice"),
    path("stato/", pagine.stato, name="stato"),
    path("agenti/", pagine.elenco_agenti, name="agenti"),
    path("operazioni/", pagine.elenco_operazioni, name="operazioni"),
    path("approvazioni/", pagine.elenco_approvazioni, name="approvazioni"),
    path("mcp/", mcp.mcp, name="mcp"),
    path("agate-webhook/", webhook.ricevi, name="agate_webhook"),
]
