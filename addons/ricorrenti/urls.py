from django.urls import path

from . import pagine

urlpatterns = [
    path("cruscotto/", pagine.cruscotto, name="cruscotto"),
    path("adeguamento/", pagine.adeguamento, name="adeguamento"),
]
