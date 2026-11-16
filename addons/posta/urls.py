from django.urls import path

from . import pagine

urlpatterns = [
    path("", pagine.caselle, name="caselle"),
    path("collega/<str:tipo>/", pagine.collega, name="collega"),
    path("ritorno/", pagine.ritorno, name="ritorno"),
    path("casella/<int:pk>/imposta/", pagine.imposta, name="imposta"),
    path("casella/<int:pk>/sincronizza/", pagine.sincronizza, name="sincronizza"),
    path("casella/<int:pk>/scollega/", pagine.scollega, name="scollega"),
    path("feed/rinnova/", pagine.feed_rinnova, name="feed_rinnova"),
    path("feed/<str:token>.ics", pagine.feed, name="feed"),
]
