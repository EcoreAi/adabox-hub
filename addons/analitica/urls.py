from django.urls import path

from . import pagine

urlpatterns = [
    path("imputa/", pagine.imputa, name="imputa"),
    path("report/", pagine.report, name="report"),
]
