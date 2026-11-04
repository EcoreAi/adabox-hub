from django.urls import path

from . import api, pagine

urlpatterns = [
    path("api/sincronizza/", api.sincronizza, name="api_sincronizza"),
    path("api/pacchetto/<slug:slug>/<str:versione>/", api.pacchetto, name="api_pacchetto"),
    path("carica/", pagine.carica, name="carica"),
]
