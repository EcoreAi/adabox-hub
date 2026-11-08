"""Il chiosco all'ingresso e la lista dei presenti."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("chiosco/", pagine.chiosco, name="chiosco"),
    path("chiosco/uscita/<int:pk>/", pagine.chiosco_uscita, name="chiosco_uscita"),
    path("presenti/", pagine.presenti, name="presenti"),
]
