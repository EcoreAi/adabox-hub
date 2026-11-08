from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "theme"
urlpatterns = [
    path("favicon.svg", views.favicon, name="favicon"),
    path("icona-<int:lato>.png", views.icona, name="icona"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="sw"),
    path("offline/", views.offline, name="offline"),
    # i browser chiedono /favicon.ico anche senza <link rel="icon">
    path("favicon.ico", RedirectView.as_view(pattern_name="theme:favicon", permanent=True)),
]
