from django.urls import path

from . import pagine

urlpatterns = [
    path("preventivo/<str:token>/", pagine.preventivo_online, name="preventivo_online"),
]
