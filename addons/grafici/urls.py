from django.urls import path

from . import costruttore, pagine

urlpatterns = [
    path("", pagine.pagine, name="pagine"),
    path("nuova/", pagine.nuova, name="nuova"),
    path("costruttore/", costruttore.costruttore, name="costruttore"),
    path("grafico/<int:pk>/costruttore/", costruttore.costruttore, name="grafico_costruttore"),
    path("pagina/<int:pk>/", pagine.pagina, name="pagina"),
    path("pagina/<int:pk>/layout/", pagine.layout, name="layout"),
    path("pagina/<int:pk>/modifica/", pagine.modifica, name="modifica"),
    path("pagina/<int:pk>/elimina/", pagine.elimina, name="elimina"),
    path("pagina/<int:pk>/condividi/", pagine.condividi, name="condividi"),
    path("pagina/<int:pk>/sposta/", pagine.sposta, name="sposta"),
    path("pagina/<int:pk>/ripristina/", pagine.ripristina, name="ripristina"),
    path("pagina/<int:pk>/aggiorna/", pagine.aggiorna_pagina, name="aggiorna_pagina"),
    path("app/<slug:app>/", pagine.pagina_app, name="pagina_app"),
    path("app/<slug:app>/layout/", pagine.layout_app, name="layout_app"),
    path("app/<slug:app>/nascondi/", pagine.nascondi_app, name="nascondi_app"),
    path("grafico/<int:pk>/", pagine.grafico, name="grafico"),
    path("grafico/<int:pk>/aggiorna/", pagine.grafico_aggiorna, name="grafico_aggiorna"),
    path("grafico/<int:pk>/tipo/", pagine.grafico_tipo, name="grafico_tipo"),
    path("grafico/<int:pk>/modifica/", pagine.grafico_modifica, name="grafico_modifica"),
    path("grafico/<int:pk>/elimina/", pagine.grafico_elimina, name="grafico_elimina"),
    path("grafico/<int:pk>/csv/", pagine.grafico_csv, name="grafico_csv"),
    path("grafico/<int:pk>/pagine/", pagine.grafico_pagine, name="grafico_pagine"),
    path("grafico/<int:pk>/condividi/", pagine.grafico_condividi, name="grafico_condividi"),
    path("salva/artifact/", pagine.salva_da_artifact, name="salva_da_artifact"),
    path("salva/vista/", pagine.salva_da_vista, name="salva_da_vista"),
]
