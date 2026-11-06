from django.urls import path

from . import pagine

urlpatterns = [
    path("", pagine.liquidazione, name="liquidazione"),
    path("periodo/<int:anno>/<str:periodicita>/<int:periodo>/", pagine.periodo, name="periodo"),
    path("periodo/<int:anno>/<str:periodicita>/<int:periodo>/chiudi/", pagine.chiudi, name="chiudi"),
    path("periodo/<int:anno>/<str:periodicita>/<int:periodo>/riapri/", pagine.riapri, name="riapri"),
    path("periodo/<int:anno>/<str:periodicita>/<int:periodo>/versata/", pagine.versata, name="versata"),
    path("lipe/", pagine.lipe, name="lipe"),
    path("detraibilita/<int:pk>/", pagine.detraibilita, name="detraibilita"),
]
