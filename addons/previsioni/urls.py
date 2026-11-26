from django.urls import path

from . import views

urlpatterns = [
    path("servizio/", views.pagina_servizio, name="servizio"),
    path("", views.pagina, name="pagina"),
    path("aggiorna/", views.aggiorna, name="aggiorna"),
    path("pronta/<str:chiave>/", views.pronta, name="pronta"),
    path("prodotto/<int:pk>/vendite/", views.prodotto_vendite, name="prodotto_vendite"),
]
