from django.urls import path

from . import views

urlpatterns = [
    path("servizio/", views.pagina_servizio, name="servizio"),
]
