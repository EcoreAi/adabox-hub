from django.urls import path

from . import pagine

urlpatterns = [
    path("nuova/", pagine.nuova, name="nuova"),
    path("distinta/<int:pk>/file/", pagine.scarica, name="file"),
    path("distinta/<int:pk>/presenta/", pagine.presenta, name="presenta"),
    path("distinta/<int:pk>/esiti/", pagine.esiti, name="esiti"),
    path("conto/<int:pk>/impostazioni/", pagine.config_conto, name="config_conto"),
    path("contatto/<int:pk>/coordinate/", pagine.coordinate, name="coordinate"),
]
