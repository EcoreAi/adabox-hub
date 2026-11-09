from django.urls import path

from . import pagine

urlpatterns = [
    path("preventivo/<str:token>/", pagine.preventivo_online, name="preventivo_online"),
    path("contatto/<int:pk>/condizioni/", pagine.condizioni_contatto, name="condizioni_contatto"),
    path("ordine/<int:pk>/modello/", pagine.applica_modello, name="applica_modello"),
]

from django.apps import apps  # noqa: E402

if apps.is_installed("crm"):
    urlpatterns += [path("da-opportunita/<int:pk>/", pagine.da_opportunita, name="da_opportunita")]

if apps.is_installed("portale"):
    from . import portale

    urlpatterns += [
        path("portale/", portale.ordini, name="portale_ordini"),
        path("portale/<int:pk>/pdf/", portale.pdf, name="portale_pdf"),
    ]
