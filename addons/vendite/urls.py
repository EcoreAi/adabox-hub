from django.urls import path

from . import pagine

urlpatterns = [
    path("preventivo/<str:token>/", pagine.preventivo_online, name="preventivo_online"),
]

from django.apps import apps  # noqa: E402

if apps.is_installed("portale"):
    from . import portale

    urlpatterns += [
        path("portale/", portale.ordini, name="portale_ordini"),
        path("portale/<int:pk>/pdf/", portale.pdf, name="portale_pdf"),
    ]
