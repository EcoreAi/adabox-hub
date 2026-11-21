from django.urls import path

from . import abbonamenti, pagine

urlpatterns = [
    path("api/eventi/", abbonamenti.elenco_eventi, name="api_eventi"),
    path("api/abbonamenti/", abbonamenti.abbona, name="api_abbona"),
    path("api/abbonamenti/<int:pk>/", abbonamenti.disdici, name="api_disdici"),
    path("account/", pagine.account, name="account"),
    path("account/<int:pk>/collega/", pagine.collega, name="account_collega"),
    path("account/<int:pk>/sincronizza/", pagine.sincronizza, name="account_sincronizza"),
    path("account/<int:pk>/scollega/", pagine.scollega, name="account_scollega"),
]
