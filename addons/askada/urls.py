from django.urls import path

from . import pagine

urlpatterns = [
    path("apri/", pagine.apri, name="apri"),
    path("chiedi/", pagine.chiedi, name="chiedi"),
]
