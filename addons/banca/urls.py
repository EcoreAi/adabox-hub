from django.urls import path

from . import collega, pagine

urlpatterns = [
    path("riconcilia/", pagine.riconcilia, name="riconcilia"),
    path("importa/", pagine.importa, name="importa"),
    path("abbina-sicuri/", pagine.abbina_sicuri, name="abbina_sicuri"),
    path("movimento/<int:pk>/scegli/", pagine.scegli, name="scegli"),
    path("movimento/<int:pk>/abbina/", pagine.abbina, name="abbina"),
    path("movimento/<int:pk>/ignora/", pagine.ignora, name="ignora"),
    path("movimento/<int:pk>/classifica/", pagine.classifica, name="classifica"),
    path("regole/applica/", pagine.applica_regole, name="applica_regole"),
    path("movimento/<int:pk>/ripristina/", pagine.ripristina, name="ripristina"),
    path("abbinamento/<int:pk>/annulla/", pagine.annulla, name="annulla"),
    path("conto/<int:pk>/collega/", collega.collega, name="collega"),
    path("collegamento/<int:pk>/ritorno/", collega.ritorno, name="collega_ritorno"),
    path("collegamento/<int:pk>/leggi/", collega.leggi_ora, name="collega_leggi"),
    path("collegamento/<int:pk>/scollega/", collega.scollega, name="scollega"),
]
