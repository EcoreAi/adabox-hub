from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("stile/", views.stile, name="stile"),
    path("profilo/", views.profilo, name="profilo"),
]
