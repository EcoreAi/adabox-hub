from django.urls import path

from . import pagine

urlpatterns = [
    path("rate/<int:pk>/paga/", pagine.paga, name="paga"),
    path("finanziamenti/<int:pk>/estingui/", pagine.estingui, name="estingui"),
]
