from django.urls import path

from . import pagine

urlpatterns = [path("verifica/", pagine.verifica, name="verifica")]
