from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "theme"
urlpatterns = [
    path("favicon.svg", views.favicon, name="favicon"),
    # i browser chiedono /favicon.ico anche senza <link rel="icon">
    path("favicon.ico", RedirectView.as_view(pattern_name="theme:favicon", permanent=True)),
]
