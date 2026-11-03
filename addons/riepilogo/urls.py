from django.urls import path

from . import pagine

urlpatterns = [
    path("", pagine.pagina, name="pagina"),
    path("pannello/", pagine.pannello, name="pannello"),
    path("preferenza/", pagine.preferenza, name="preferenza"),
]
