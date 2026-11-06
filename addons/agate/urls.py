"""Pagine del modulo Agate, montate dal kernel sotto /agate/ (namespace agate)."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("", pagine.stato, name="stato"),
    path("valutazioni/", pagine.valutazioni, name="valutazioni"),
    path("da-approvare/", pagine.da_approvare, name="da_approvare"),
    path("impostazioni/", pagine.impostazioni, name="impostazioni"),
    path("webhook/", pagine.webhook, name="webhook"),
]
