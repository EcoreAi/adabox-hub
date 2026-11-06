from django.urls import path

from . import pagine

urlpatterns = [
    path("", pagine.regole, name="regole"),
    path("nuova/", pagine.regola_form, name="regola_nuova"),
    path("<int:pk>/", pagine.regola, name="regola"),
    path("<int:pk>/modifica/", pagine.regola_form, name="regola_modifica"),
    path("<int:pk>/attiva/", pagine.regola_attiva, name="regola_attiva"),
    path("<int:pk>/disattiva/", pagine.regola_disattiva, name="regola_disattiva"),
    path("<int:pk>/elimina/", pagine.regola_elimina, name="regola_elimina"),
    path("<int:pk>/prova/", pagine.regola_prova, name="regola_prova"),
    path("pronte/<str:codice>/", pagine.ricetta, name="ricetta"),
    path("storico/", pagine.storico, name="storico"),
    path("storico/<int:pk>/riprova/", pagine.riprova, name="riprova"),
    path("modelli/", pagine.modelli, name="modelli"),
    path("modelli/elenco/", pagine.modelli_elenco, name="modelli_elenco"),
    path("modelli/nuovo/", pagine.modello_nuovo, name="modello_nuovo"),
    path("modelli/anteprima/", pagine.modello_anteprima, name="modello_anteprima"),
    path("modelli/<str:codice>/", pagine.modello, name="modello"),
    path("modelli/<str:codice>/prova/", pagine.modello_prova, name="modello_prova"),
    path("modelli/<str:codice>/ripristina/", pagine.modello_ripristina, name="modello_ripristina"),
]
