from django.urls import path

from . import pagine

urlpatterns = [
    path("casse/<int:pk>/chiudi/", pagine.chiudi, name="chiudi"),
]
