"""Pagine di AWF, montate dal kernel sotto /awf/ (namespace awf). Il server MCP e il webhook di Agate non usano la
sessione: si autenticano con il bearer e con la firma."""
from django.urls import path
from django.views.generic import RedirectView

from . import area, mcp, pagine, webhook

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="awf:negozio"), name="indice"),
    # l'area «Agenti AI»
    path("negozio/", area.negozio, name="negozio"),
    path("negozio/<slug:slug>/", area.scheda, name="scheda"),
    path("assumi/<slug:slug>/", area.assumi, name="assumi"),
    path("richieste/", area.richieste, name="richieste"),
    path("richieste/<int:pk>/", area.richiesta, name="richiesta"),
    path("miei/", area.miei, name="miei"),
    path("miei/<int:pk>/cosa-puo-fare/", area.cosa_puo_fare, name="cosa_puo_fare"),
    path("miei/<int:pk>/persone/", area.persone, name="persone"),
    path("avanzate/", area.avanzate, name="avanzate"),
    path("catalogo/", RedirectView.as_view(pattern_name="awf:negozio", query_string=True), name="catalogo"),
    # Avanzate: le pagine tecniche
    path("stato/", pagine.stato, name="stato"),
    path("agenti/", pagine.elenco_agenti, name="agenti"),
    path("operazioni/", pagine.elenco_operazioni, name="operazioni"),
    path("approvazioni/", pagine.elenco_approvazioni, name="approvazioni"),
    path("mcp/", mcp.mcp, name="mcp"),
    path("agate-webhook/", webhook.ricevi, name="agate_webhook"),
]
