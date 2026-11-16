from django.urls import path

from . import pagine

urlpatterns = [path("pagine/<int:pk>/versione/<int:numero>/ripristina/", pagine.ripristina, name="ripristina"),
               path("chiedi/", pagine.chiedi, name="chiedi")]
