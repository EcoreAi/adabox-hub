from django.urls import path

from . import pagine

urlpatterns = [
    path("contatto/<int:pk>/consenso/", pagine.consenso, name="consenso"),
    path("contatto/<int:pk>/esporta/", pagine.esporta, name="esporta"),
    path("contatto/<int:pk>/anonimizza/", pagine.anonimizza, name="anonimizza"),
]
