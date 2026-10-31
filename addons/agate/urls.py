"""Pagine del modulo Agate, montate dal kernel sotto /agate/ (namespace agate)."""
from django.urls import path

from . import pagine

urlpatterns = [
    path("", pagine.collegamento, name="collegamento"),
    path("valutazioni/", pagine.valutazioni, name="valutazioni"),
    path("webhook/", pagine.webhook, name="webhook"),
]
