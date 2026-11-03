from django.urls import path

from . import pagine

urlpatterns = [
    path("riconcilia/", pagine.riconcilia, name="riconcilia"),
    path("importa/", pagine.importa, name="importa"),
    path("abbina-sicuri/", pagine.abbina_sicuri, name="abbina_sicuri"),
    path("movimento/<int:pk>/scegli/", pagine.scegli, name="scegli"),
    path("movimento/<int:pk>/abbina/", pagine.abbina, name="abbina"),
    path("movimento/<int:pk>/ignora/", pagine.ignora, name="ignora"),
    path("movimento/<int:pk>/ripristina/", pagine.ripristina, name="ripristina"),
    path("abbinamento/<int:pk>/annulla/", pagine.annulla, name="annulla"),
]
