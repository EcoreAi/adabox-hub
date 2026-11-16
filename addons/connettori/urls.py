from django.urls import path

from . import pagine

urlpatterns = [
    path("account/", pagine.account, name="account"),
    path("account/<int:pk>/collega/", pagine.collega, name="account_collega"),
    path("account/<int:pk>/sincronizza/", pagine.sincronizza, name="account_sincronizza"),
    path("account/<int:pk>/scollega/", pagine.scollega, name="account_scollega"),
]
