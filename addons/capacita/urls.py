from django.urls import path

from . import pagine

urlpatterns = [
    path("consegne/", pagine.consegne, name="consegne"),
    path("carico/", pagine.carico, name="carico"),
    path("gantt/", pagine.gantt, name="gantt"),
    path("simula/", pagine.simula, name="simula"),
]
